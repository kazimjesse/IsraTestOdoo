import logging
import base64
import io
import uuid

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class KnowledgeDocument(models.Model):
    _name = 'knowledge.document'
    _description = 'Documento de Base de Conocimiento'

    name = fields.Char(string='Nombre del Documento', required=True)
    file = fields.Binary(string='Archivo PDF', required=True)
    file_name = fields.Char(string='Nombre del archivo')
    texto = fields.Text(string='Texto Extraído', readonly=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('processed', 'Procesado y en Qdrant')
    ], string='Estado', default='draft', readonly=True)

    def action_procesar_documento(self):
        self.ensure_one()
        _logger.info('Iniciando procesamiento de documento: %s (ID: %s)', self.name, self.id)
        if not self.file:
            raise UserError('Por favor adjunta un archivo PDF.')

        try:
            import PyPDF2
        except ImportError:
            raise UserError('Pip install PyPDF2 requerido.')

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import PointStruct, VectorParams, Distance
        except ImportError:
            raise UserError('Pip install qdrant-client requerido. Odoo.sh debería instalarlo desde requirements.txt.')

        try:
            from google import genai
        except ImportError:
            raise UserError('Pip install google-genai requerido.')

        # Extract Text
        _logger.debug('Extrayendo texto del PDF con PyPDF2...')
        pdf_data = base64.b64decode(self.file)
        pdf_file = io.BytesIO(pdf_data)
        reader = PyPDF2.PdfReader(pdf_file)
        
        texto_completo = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texto_completo += t + "\n"

        if not texto_completo.strip():
            _logger.warning('No se pudo extraer texto del PDF %s. Quizás sea una imagen escaneada.', self.name)
            raise UserError('No se pudo extraer texto del PDF.')
        
        self.texto = texto_completo.strip()
        _logger.info('Texto extraído exitosamente. Longitud: %d caracteres.', len(self.texto))

        # Config parameters
        api_key = self.env['ir.config_parameter'].sudo().get_param('gemini_api_key')
        qdrant_url = self.env['ir.config_parameter'].sudo().get_param('qdrant_url')
        qdrant_api_key = self.env['ir.config_parameter'].sudo().get_param('qdrant_api_key')

        if not api_key:
            _logger.error('El parámetro gemini_api_key no existe en Odoo.')
            raise UserError('Falta "gemini_api_key" en Parámetros del Sistema.')
        if not qdrant_url or not qdrant_api_key:
            _logger.error('Parámetros de Qdrant faltantes en la configuración.')
            raise UserError('Faltan "qdrant_url" y "qdrant_api_key" en Parámetros del Sistema.')

        # Chunking: split text roughly every 800-1000 characters without breaking words
        _logger.debug('Iniciando proceso de chunking del texto...')
        chunks = []
        current_chunk = ""
        for word in texto_completo.split():
            current_chunk += word + " "
            if len(current_chunk) > 800:
                chunks.append(current_chunk.strip())
                current_chunk = ""
        if current_chunk:
            chunks.append(current_chunk.strip())
        _logger.info('Chunking finalizado. Se generaron %d fragmentos para vectorización.', len(chunks))

        # Embedding & Qdrant insertion
        _logger.info('Conectando a Gemini y Qdrant...')
        client = genai.Client(api_key=api_key)
        qd_client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        
        collection_name = "knowledge_base"
        
        # Check if collection exists, if not create
        if not qd_client.collection_exists(collection_name):
            _logger.info('La colección %s no existe en Qdrant. Creándola...', collection_name)
            qd_client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )

        _logger.info('Enviando fragmentos a Gemini para generar Embeddings...')
        points = []
        for i, chunk in enumerate(chunks):
            # Generate embedding
            response = client.models.embed_content(
                model='text-embedding-004',
                contents=chunk
            )
            vector = response.embeddings[0].values
            
            # Create Qdrant Point
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={"document_id": self.id, "document_name": self.name, "text": chunk}
                )
            )

        if points:
            _logger.info('Embeddings generados exitosamente. Subiendo %d puntos a Qdrant...', len(points))
            qd_client.upsert(
                collection_name=collection_name,
                points=points
            )
            _logger.info('Subida a Qdrant completada para el documento %s.', self.name)

        self.state = 'processed'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Documento Procesado',
                'message': f'Se generaron y guardaron {len(points)} vectores en Qdrant.',
                'type': 'success',
                'sticky': False,
            }
        }
