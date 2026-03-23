import logging
import json

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class KnowledgeConsulta(models.Model):
    _name = 'knowledge.consulta'
    _description = 'Consulta a la Base de Conocimiento'

    name = fields.Char(string='Referencia / Título', required=True, default='Nueva Consulta')
    prompt = fields.Text(string='Pregunta', required=True)
    resultado = fields.Text(string='Respuesta del Asistente', readonly=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Consultado')
    ], string='Estado', default='draft', readonly=True)

    def action_consultar(self):
        self.ensure_one()
        _logger.info('Iniciando consulta en Knowledge Base: "%s"', self.prompt)
        if not self.prompt:
            raise UserError('Escribe una pregunta.')

        try:
            from qdrant_client import QdrantClient
        except ImportError:
            raise UserError('Pip install qdrant-client requerido. En Odoo.sh se instalará mediante requirements.txt.')

        try:
            from google import genai
        except ImportError:
            raise UserError('Pip install google-genai requerido.')

        api_key = self.env['ir.config_parameter'].sudo().get_param('gemini_api_key')
        qdrant_url = self.env['ir.config_parameter'].sudo().get_param('qdrant_url')
        qdrant_api_key = self.env['ir.config_parameter'].sudo().get_param('qdrant_api_key')

        if not api_key or not qdrant_url or not qdrant_api_key:
            _logger.error('Faltan parámetros de configuración del sistema (gemini_api_key, qdrant_url o qdrant_api_key).')
            raise UserError('Faltan configuraciones de Gemini o Qdrant en Parámetros del Sistema.')

        client = genai.Client(api_key=api_key)
        qd_client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        collection_name = "knowledge_base_v2"

        # 1. Embed the prompt
        try:
            _logger.info('Solicitando embedding de la pregunta a Gemini...')
            response_embed = client.models.embed_content(
                model='gemini-embedding-001',
                contents=self.prompt
            )
            query_vector = response_embed.embeddings[0].values
            _logger.debug('Embedding generado correctamente para la pregunta.')
        except Exception as e:
            _logger.error('Error generando el embedding de la pregunta: %s', str(e))
            raise UserError(f'Error al generar embedding de la pregunta: {str(e)}')

        # 2. Search in Qdrant
        try:
            _logger.info('Buscando coincidencias en la colección "%s" de Qdrant...', collection_name)
            if not qd_client.collection_exists(collection_name):
                _logger.warning('La colección %s no existe en Qdrant aún.', collection_name)
                raise UserError('La base de datos Qdrant está vacía. Sube documentos primero.')
                
            search_result = qd_client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=5
            )
            _logger.info('Búsqueda completada, se encontraron %d posibles fragmentos relevantes.', len(search_result))
        except Exception as e:
            if isinstance(e, UserError):
                raise
            _logger.error('Error buscando vectores en Qdrant: %s', str(e))
            raise UserError(f'Error al buscar en Qdrant: {str(e)}')

        if not search_result:
            _logger.info('No se encontraron resultados en Qdrant para la pregunta planteada.')
            self.resultado = "No encontré información relevante en la base de conocimiento para esta pregunta."
            self.state = 'done'
            return

        # 3. Construct context
        _logger.debug('Construyendo prompt enriquecido con contexto recuperado de Qdrant...')
        context_parts = []
        for hit in search_result:
            payload = hit.payload
            doc_name = payload.get('document_name', 'Documento Desconocido')
            text_chunk = payload.get('text', '')
            context_parts.append(f"--- Documento: {doc_name} ---\n{text_chunk}")
            
        context_str = "\n\n".join(context_parts)

        # 4. Ask Gemini
        prompt_final = f"""Eres un asistente corporativo experto.
Tu objetivo es responder de manera clara y precisa a la pregunta del usuario basándote ESTRICTAMENTE en los siguientes fragmentos de manuales oficiales.
Si la respuesta no está en los fragmentos proveídos, debes decir claramente que no tienes esa información y no debes inventarla.

INFORMACIÓN DE CONTEXTO OFICIAL:
{context_str}

PREGUNTA DEL USUARIO:
{self.prompt}
"""
        try:
            _logger.info('Enviando prompt de %d caracteres a Gemini-1.5-flash para obtener la respuesta final...', len(prompt_final))
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt_final,
                config={
                    'temperature': 0.1,
                }
            )
            self.resultado = response.text
            self.state = 'done'
            _logger.info('Respuesta final recibida y guardada exitosamente.')
        except Exception as e:
            _logger.error('Error durante la generación de contenido en Gemini: %s', str(e))
            raise UserError(f'Error al generar respuesta con Gemini: {str(e)}')
