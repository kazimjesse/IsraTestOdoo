import logging
import json
import os

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

def llamar_gemini(prompt, api_key):
    try:
        from google import genai
    except ImportError:
        raise ImportError("google-genai")

    client = genai.Client(api_key=api_key)
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config={
            'temperature': 0.2,
            'max_output_tokens': 1024,
        }
    )

    return response.text


class ResumeConsulta(models.Model):
    _name = 'resume.consulta'
    _description = 'Consulta de CVs con IA'

    subject = fields.Char(string='Asunto')
    area = fields.Selection(AREA_SELECTION, string='Área (filtro)', required=False)
    prompt = fields.Text(string='Requerimiento')
    resultado = fields.Text(string='Respuesta de la IA', readonly=True)
    state = fields.Selection(
        [('draft', 'Borrador'), ('processing', 'Procesando'), ('done', 'Completado')],
        string='Estado',
        default='draft',
        readonly=True,
    )
    line_ids = fields.One2many('resume.consulta.line', 'consulta_id', string='Candidatos Seleccionados')

    def action_consultar_ia(self):
        self.ensure_one()
        _logger.info('Iniciando consulta a la IA (ID: %s) para el área: %s', self.id, self.area or 'Todas')

        if not self.prompt:
            raise UserError('Escribe un requerimiento antes de consultar la IA.')

        self.write({'state': 'processing', 'line_ids': [(5, 0, 0)], 'resultado': False})

        # Filtrar CVs por área si se especifica
        domain = [('texto', '!=', False), ('texto', '!=', '')]
        if self.area:
            domain.append(('area', '=', self.area))

        cvs = self.env['resume.cv'].search(domain, limit=10)
        _logger.debug('Se encontraron %d CVs para la consulta (dominio: %s)', len(cvs), domain)

        if not cvs:
            area_label = dict(AREA_SELECTION).get(self.area, self.area) if self.area else 'todas las áreas'
            raise UserError(
                f'No hay CVs procesados disponibles para {area_label}. '
                'Sube y procesa CVs primero usando el botón "Procesar CV".'
            )

        # Construir contexto con máximo 500 caracteres por CV
        partes_contexto = []
        for cv in cvs:
            texto_truncado = (cv.texto or '')[:500]
            partes_contexto.append(f'--- CV: {cv.name} (Área: {cv.area}) ---\n{texto_truncado}')

        contexto = '\n\n'.join(partes_contexto)
        _logger.debug('Contexto de CVs construido correctamente. Longitud total: %d caracteres.', len(contexto))

        num_candidatos = min(3, len(cvs))
        
        prompt_final = f"""Eres un reclutador experto.

Analiza los siguientes CVs y devuelve los {num_candidatos} mejores candidatos según este requerimiento:

REQUERIMIENTO:
{self.prompt}

CVs:
{contexto}

Devuelve SOLO JSON válido en este formato, sin texto adicional, sin markdown, sin explicaciones:

[
  {{
    "nombre": "",
    "telefono": "",
    "score": 0,
    "resumen": ""
  }}
]"""

        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('gemini_api_key')
            if not api_key:
                _logger.warning('No se encontró el parámetro de sistema "gemini_api_key".')
                raise ValueError('La clave de API de Gemini no está configurada. Usa Odoo UI (Ajustes > Técnico > Parámetros del sistema) para agregar "gemini_api_key".')

            _logger.info('Enviando request a Gemini... Promt final tiene %d caracteres.', len(prompt_final))
            respuesta_texto = llamar_gemini(prompt_final, api_key)
            _logger.info('Respuesta de Gemini recibida (%d caracteres)', len(respuesta_texto))
        except ValueError as e:
            self.write({'state': 'draft'})
            raise UserError(str(e))
        except ImportError:
            self.write({'state': 'draft'})
            raise UserError('La librería google-genai no está instalada. Ejecuta: pip install google-genai')
        except Exception as e:
            self.write({'state': 'draft'})
            _logger.error('Error llamando a Gemini: %s', str(e))
            raise UserError(f'Error al contactar la IA: {str(e)}')

        # Parsear JSON
        _logger.info('Iniciando limpieza y parseo del JSON recibido de Gemini.')
        candidatos = []
        try:
            texto_limpio = respuesta_texto.strip()
            
            # Extraer solo la parte que parece un array JSON
            inicio = texto_limpio.find('[')
            fin = texto_limpio.rfind(']')
            
            if inicio != -1 and fin != -1:
                texto_limpio = texto_limpio[inicio:fin+1]
            else:
                raise ValueError('No se encontró un arreglo JSON en la respuesta de la IA.')

            candidatos = json.loads(texto_limpio)
            if not isinstance(candidatos, list):
                raise ValueError('La respuesta no es una lista JSON.')
        except (json.JSONDecodeError, ValueError) as e:
            _logger.error('JSON inválido recibido de Gemini: %s', respuesta_texto)
            self.write({
                'state': 'done',
                'resultado': f'Error al parsear respuesta JSON.\n\nRespuesta raw:\n{respuesta_texto}',
            })
            return

        # Crear líneas de resultado
        lineas = []
        for c in candidatos:
            if not isinstance(c, dict):
                continue
            lineas.append((0, 0, {
                'nombre': c.get('nombre', ''),
                'telefono': c.get('telefono', ''),
                'score': float(c.get('score', 0)),
                'resumen': c.get('resumen', ''),
            }))

        self.write({
            'state': 'done',
            'resultado': respuesta_texto,
            'line_ids': lineas,
        })

        _logger.info('Parseo exitoso. Consulta %s completada con %d candidatos insertados.', self.subject or self.id, len(lineas))
