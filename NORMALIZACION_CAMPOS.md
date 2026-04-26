# Normalización de campos de plantillas

## Criterio adoptado

- Nombres técnicos en `camelCase`.
- Sin tildes ni espacios.
- Un único nombre por dato, aunque en Word aparezca en mayúsculas o negrita.
- La presentación final se hereda de la plantilla:
  - si el marcador está en negrita, el valor se insertará en negrita;
  - si el marcador está en mayúsculas, el valor se transformará a mayúsculas;
  - si el marcador no tiene estilo especial, se insertará tal cual.

## Campos normalizados

| Campo normalizado | Significado | Variantes detectadas |
| --- | --- | --- |
| `nombreAlumno` | Nombre completo del alumno/a | `NOMBREALUMNO`, `nombreAlumno` |
| `cursoAlumno` | Curso del alumno/a | `cursoAlumno` |
| `grupoAlumno` | Grupo/unidad del alumno/a | `GRUPOALUMNO`, `grupoAlumno` |
| `diaHechos` | Día de los hechos | `diaHecho`, `diaHechos` |
| `mesHechos` | Mes de los hechos | `mesHecho`, `mesHechos`, `meshechos` |
| `hechos` | Relato breve o literal de los hechos | `hechos`, `HECHOS` |
| `nombreInstructor` | Nombre completo del instructor/a | `NOMBREINSTRUCTOR`, `nombreInstructor`, `nombreinstructor` |
| `nombrePadres` | Nombre de representantes legales | `nombrePadres` |
| `nombreTutores` | Nombre de representantes legales en plural | `nombreTutores` |
| `fechaApertura` | Día o fecha de apertura del expediente | `fechaApertura` |
| `mesApertura` | Mes de apertura del expediente | `mesApertura` |
| `cargoPrimero` | Primer cargo | `cargoPrimero` |
| `cargoSegundo` | Segundo cargo | `cargoSegundo` |
| `cargoTercero` | Tercer cargo | `cargoTercero` |
| `horasVisita` | Hora del acto de vista/audiencia | `horasVisita` |
| `diaVisita` | Día del acto de vista/audiencia | `diaVisita` |
| `mesVisita` | Mes del acto de vista/audiencia | `mesVisita` |
| `lugarCita` | Lugar de citación | `lugarCita` |
| `fechaHoraCita` | Fecha y hora de la citación | `día y hora cita` |
| `hechosImputados` | Texto de hechos imputados | `hechosImputados` |
| `calificacionHechos` | Calificación jurídica/disciplinaria | `calificacionHechos` |
| `propuesta` | Texto breve de propuesta de resolución | `propuesta` |
| `diasSuspension` | Número de días de suspensión | `diasSuspension` |
| `diasExpulsionCautelar` | Número de días de medida provisional | `diasexpulsióncautelar` |

## Decisiones de consolidación

- `nombreTutores` debe integrarse en `nombrePadres`.
  - Motivo: funcionalmente ambos campos representan a los representantes legales.
- `fechaApertura` y `mesApertura` deberían evolucionar a una única `fechaApertura`.
  - Si la plantilla exige separar día y mes, el generador puede derivarlos desde una fecha.
- `diaHechos` y `mesHechos` podrían derivarse también desde una única `fechaHechos`.
  - Para compatibilidad con las plantillas actuales se mantienen ambos.
- `fechaHoraCita` sustituye a `día y hora cita`.
  - Motivo: el nombre actual tiene espacios y tilde, lo que complica automatización.

## Uso por plantilla

### 01 - Sanción Incio Expediente.docx

- `nombreAlumno`
- `cursoAlumno`
- `grupoAlumno`
- `diaHechos`
- `mesHechos`
- `hechos`
- `nombreInstructor`

### 02 - Sanción Notificación Inicio Expediente.docx

- `diaHechos`
- `mesHechos`
- `nombreAlumno`
- `cursoAlumno`
- `grupoAlumno`

### 03 - Sanción Propuesta de Medidas.docx

- `nombreAlumno`
- `diaHechos`
- `mesHechos`
- `nombreInstructor`

### 04 - Sanción Medidas Provisionales.docx

- `nombreAlumno`
- `diaHechos`
- `mesHechos`
- `diasExpulsionCautelar`
- `nombrePadres`

### 05 - Sanción Citación.docx

- `nombreAlumno`
- `grupoAlumno`
- `diaHechos`
- `mesHechos`
- `hechos`
- `nombrePadres`
- `lugarCita`
- `fechaHoraCita`
- `nombreInstructor`

### 06 - Sanción Pliego de cargos.docx

- `nombreInstructor`
- `nombreAlumno`
- `fechaApertura`
- `mesApertura`
- `cargoPrimero`
- `cargoSegundo`
- `cargoTercero`
- `nombrePadres`

### 07 - Sanción Vista y Audiencia.docx

- `horasVisita`
- `diaVisita`
- `mesVisita`
- `nombreAlumno`
- `nombreInstructor`
- `nombrePadres`

### 08 - Sanción Notificación propuesta resolución.docx

- `nombreAlumno`
- `grupoAlumno`
- `nombreInstructor`
- `nombrePadres`

### 09 - Sanción Propuesta de resolución.docx

- `diaHechos`
- `nombreAlumno`
- `nombreInstructor`
- `hechosImputados`
- `calificacionHechos`
- `propuesta`
- `diasSuspension`

### 10 - Sanción Notificación acuerdo Consejo Escolar.docx

- `diaConsejoEscolar`
- `mesConsejoEscolar`
- `nombreAlumno`
- `hechos`
- `diasSuspension`

### 11 - Notificacion familias.docx

- `nombreAlumno`
- `hechos`
- `diasSuspension`
- `nombrePadres`

### 12 - Notificacion inspeccion.docx

- `nombreAlumno`
- `hechos`
- `diasSuspension`

## Campos detectados fuera de la tabla inicial

Estos campos aparecen en las plantillas 10 y no estaban en la primera tabla de búsqueda manual, pero sí existen:

| Campo normalizado | Significado | Variantes detectadas |
| --- | --- | --- |
| `diaConsejoEscolar` | Día de la sesión del Consejo Escolar | `diaConsejoEscolar` |
| `mesConsejoEscolar` | Mes de la sesión del Consejo Escolar | `mesConsejoEscolar` |

## Incidencias a corregir en los DOCX

### Marcadores inconsistentes o defectuosos

- `02 - Sanción Notificación Inicio Expediente.docx`
  - `<<NOMBREALUMNO>>` aparece partido como `<<` + `NOMBREALUMNO>>`.
  - `<<GRUPOALUMNO>>` aparece partido como `<<` + `GRUPOALUMNO>>`.
- `03 - Sanción Propuesta de Medidas.docx`
  - `<<NOMBREALUMNO>>` aparece partido como `<<` + `NOMBREALUMNO>>`.
- `04 - Sanción Medidas Provisionales.docx`
  - Usa `meshechos` en minúscula irregular.
  - Usa `diasexpulsióncautelar` con tilde.
- `05 - Sanción Citación.docx`
  - Usa `día y hora cita` con espacios y tilde.
- `06 - Sanción Pliego de cargos.docx`
  - Mezcla `nombreinstructor` y `nombreInstructor`.
- `10 - Sanción Notificación acuerdo Consejo Escolar.docx`
  - Usa `HECHOS` en mayúsculas como nombre técnico del campo.
- `11 - Notificacion familias.docx`
  - Usa `HECHOS` en mayúsculas como nombre técnico del campo.
- `12 - Notificacion inspeccion.docx`
  - Usa `NOMBREALUMNO` y `HECHOS` en mayúsculas como nombre técnico del campo.

### Recomendación de corrección en plantillas

Sustituir todos los marcadores visuales actuales por una versión canónica, manteniendo su formato:

- `<<nombreAlumno>>`
- `<<cursoAlumno>>`
- `<<grupoAlumno>>`
- `<<diaHechos>>`
- `<<mesHechos>>`
- `<<hechos>>`
- `<<nombreInstructor>>`
- `<<nombrePadres>>`
- `<<fechaApertura>>`
- `<<mesApertura>>`
- `<<cargoPrimero>>`
- `<<cargoSegundo>>`
- `<<cargoTercero>>`
- `<<horasVisita>>`
- `<<diaVisita>>`
- `<<mesVisita>>`
- `<<lugarCita>>`
- `<<fechaHoraCita>>`
- `<<hechosImputados>>`
- `<<calificacionHechos>>`
- `<<propuesta>>`
- `<<diasSuspension>>`
- `<<diasExpulsionCautelar>>`
- `<<diaConsejoEscolar>>`
- `<<mesConsejoEscolar>>`

## Recomendación técnica para la automatización

- No hacer reemplazos sobre texto plano del XML.
- Detectar secuencias completas `<<...>>` aunque Word las haya partido en varios `runs`.
- Sustituir el valor preservando el estilo del `run` dominante del marcador.
- Aplicar transformación a mayúsculas solo cuando el marcador origen esté en mayúsculas.
- Mantener un diccionario de alias temporal mientras las plantillas no estén corregidas.
