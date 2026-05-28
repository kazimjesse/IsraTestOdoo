import logging
import base64
import io

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

AREA_SELECTION = [
    ('contabilidad', 'Contabilidad'),
    ('tecnologia', 'Tecnología'),
    ('recursos_humanos', 'Recursos Humanos'),
    ('ventas', 'Ventas'),
    ('marketing', 'Marketing'),
    ('otros', 'Otros'),
]


class ResumeCv(models.Model):
    _name = 'resume.cv'
    _description = 'CV / Hoja de Vida'

    name = fields.Char(string='Nombre', readonly=True, default='Nuevo CV')
    file = fields.Binary(string='Archivo PDF', required=True)
    file_name = fields.Char(string='Nombre del archivo')
    texto = fields.Text(string='Texto extraído')
    area = fields.Selection(AREA_SELECTION, string='Área', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nuevo CV') == 'Nuevo CV':
                count = self.search_count([]) + 1
                vals['name'] = f'CV {count}'

        records = super().create(vals_list)

         # Procesar automáticamente cada CV creado
        for record in records:
            
            # Ejecutar procesamiento automático
            resultado = record.action_procesar_cv()
            
            # Imprimir resultado en logs
            _logger.info('Resultado procesamiento CV %s: %s',
            record.name,
            resultado
            )

        return records

    def action_procesar_cv(self):
        self.ensure_one()
        _logger.info('Iniciando procesamiento de CV: %s (Archivo: %s)', self.name, self.file_name)
        if not self.file:
            raise UserError('Por favor adjunta un archivo PDF antes de procesar.')

        try:
            import PyPDF2
        except ImportError:
            raise UserError('La librería PyPDF2 no está instalada. Ejecuta: pip install PyPDF2')

        try:
            pdf_data = base64.b64decode(self.file)
            pdf_file = io.BytesIO(pdf_data)
            reader = PyPDF2.PdfReader(pdf_file)

            if len(reader.pages) == 0:
                _logger.warning('El PDF %s no contiene páginas.', self.name)
                raise UserError('El PDF no contiene páginas.')

            texto_completo = []
            for page in reader.pages:
                texto_pagina = page.extract_text()
                if texto_pagina:
                    texto_completo.append(texto_pagina)

            texto_final = '\n'.join(texto_completo).strip()

            if not texto_final:
                _logger.warning('No se pudo extraer texto del PDF %s. Podría ser una imagen escaneada.', self.name)
                raise UserError('No se pudo extraer texto del PDF. El archivo puede estar escaneado o protegido.')

            self.texto = texto_final
            _logger.info('CV procesado correctamente: %s (%d caracteres)', self.name, len(texto_final))

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'CV Procesado',
                    'message': f'Se extrajeron {len(texto_final)} caracteres del PDF.',
                    'type': 'success',
                    'sticky': False,
                },
            }

        except UserError:
            raise
        except Exception as e:
            _logger.error('Error procesando PDF %s: %s', self.name, str(e))
            raise UserError(f'Error al procesar el PDF: {str(e)}')
