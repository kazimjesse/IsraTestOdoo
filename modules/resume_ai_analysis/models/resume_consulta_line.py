from odoo import models, fields


class ResumeConsultaLine(models.Model):
    _name = 'resume.consulta.line'
    _description = 'Resultado de Consulta de CV'
    _order = 'score desc'

    consulta_id = fields.Many2one('resume.consulta', string='Consulta', ondelete='cascade')
    nombre = fields.Char(string='Nombre del Candidato')
    telefono = fields.Char(string='Teléfono')
    email = fields.Char(string='Correo Electrónico')
    score = fields.Float(string='Puntuación', digits=(5, 2))
    resumen = fields.Text(string='Resumen')
