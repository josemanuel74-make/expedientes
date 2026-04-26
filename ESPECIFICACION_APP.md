# Especificación de la app de expedientes disciplinarios

## Objetivo

Aplicación web interna para gestionar expedientes disciplinarios de alumnado, con generación automática de documentos a partir de plantillas `.docx`, minimizando datos personales y endurecida para exposición en internet.

## Base normativa revisada

- Referencia revisada: `BOE-A-1995-13291-consolidado.pdf`
- Norma utilizada para ajustar el MVP: Real Decreto 732/1995, de 5 de mayo.
- Artículos relevantes para esta app:
  - artículo 5: el Consejo Escolar es el órgano competente para resolución e imposición de sanciones.
  - artículo 51: no puede corregirse una conducta gravemente perjudicial sin expediente previo.
  - artículo 52: tipifica las conductas gravemente perjudiciales.
  - artículo 53: define las correcciones posibles.
  - artículo 54: regula instructor, recusación y medidas provisionales.
  - artículo 55: regula plazos de instrucción, audiencia y comunicación a Inspección.
  - artículo 56: fija plazo máximo de resolución y recurso ordinario.

## Principios de diseño

- Minimización de datos: guardar solo lo imprescindible para tramitar el expediente.
- Seguridad por defecto: autenticación fuerte, control de acceso, auditoría y cifrado.
- Plantillas como fuente de presentación: la app rellena campos, pero el formato lo manda Word.
- Trazabilidad: cada expediente debe dejar constancia de quién hizo qué y cuándo.
- Simplicidad operativa: pocos pasos, interfaz clara, sin depender del Excel en el día a día.
- Cumplimiento procedimental: la app debe forzar los pasos mínimos exigidos por la norma.

## Alcance del MVP

### Incluye

- Alta y consulta de alumnos con datos mínimos.
- Alta y seguimiento de expedientes.
- Formularios por fases del expediente.
- Generación de documentos `.docx` desde plantillas.
- Historial de actuaciones.
- Gestión de usuarios con roles.
- Registro de auditoría.

### No incluye inicialmente

- Firma electrónica avanzada.
- Envío automático de correo o SMS.
- Integración en tiempo real con sistemas externos del ministerio.
- Portal para familias.
- Estadísticas complejas.

## Usuarios y roles

### Administrador

- Gestiona usuarios, roles, plantillas y configuración.
- Acceso completo a auditoría.

### Dirección

- Crea expedientes.
- Consulta y edita expedientes.
- Genera documentos.
- Consulta alumnado.
- Designa instructor.
- Propone o adopta medidas provisionales.

### Instructor

- Gestiona la instrucción del expediente.
- Rellena fases y genera documentos de su ámbito.
- Formula pliego de cargos y propuesta de resolución.

### Consejo Escolar

- No necesita operar como usuario autónomo en el MVP, pero la app debe registrar sus acuerdos.
- Debe quedar identificado el acuerdo de resolución y, en su caso, la revocación de medidas provisionales.

### Consulta

- Solo lectura de expedientes permitidos.

## Flujo principal

1. Buscar o dar de alta al alumno con datos mínimos.
2. Registrar fecha de conocimiento de los hechos.
3. Crear expediente disciplinario por Dirección.
4. Designar instructor.
5. Notificar incoación a padres, tutores o representantes legales.
6. Comunicar inicio a Inspección Técnica.
7. Tramitar, en su caso, medidas provisionales.
8. Instruir expediente, formular cargos y celebrar audiencia.
9. Elaborar propuesta de resolución al Consejo Escolar.
10. Registrar acuerdo del Consejo Escolar.
11. Notificar resolución a interesados e Inspección.
12. Cerrar expediente.

## Módulos de la aplicación

### 1. Autenticación y acceso

- Inicio de sesión con usuario y contraseña.
- Segundo factor obligatorio para perfiles internos.
- Cierre de sesión por inactividad.
- Restricción por rol.

### 2. Alumnado

- Alta mínima de alumno.
- Búsqueda por nombre, curso, grupo o identificador interno.
- Edición restringida de datos personales.

### 3. Expedientes

- Crear expediente.
- Ver estado.
- Editar datos del expediente.
- Consultar cronología.
- Cerrar expediente.

### 4. Fases del expediente

- Inicio de expediente.
- Notificación de inicio.
- Medidas provisionales.
- Citación.
- Pliego de cargos.
- Vista y audiencia.
- Propuesta de resolución.
- Acuerdo / notificación final.
- Notificaciones a familias e inspección.

La app debe tratar estas fases como hitos procedimentales y no solo como documentos sueltos.

### 5. Generación documental

- Selección de plantilla.
- Sustitución de marcadores `<<...>>`.
- Conservación de formato.
- Descarga de `.docx`.

### 6. Auditoría

- Registro de acceso.
- Registro de creación, edición y descarga.
- Registro de cambios de estado.

### 7. Administración

- Gestión de usuarios.
- Gestión de roles.
- Gestión de plantillas.
- Configuración de plazos y textos fijos.

### 8. Control de plazos

- Cálculo del plazo máximo de 10 días para acordar la instrucción desde el conocimiento de los hechos.
- Cálculo del plazo máximo de 7 días para la instrucción.
- Cálculo del plazo máximo de 1 mes para resolver desde el inicio.
- Alertas por vencimiento próximo.
- Bloqueo o advertencia cuando falten hitos previos obligatorios.

## Datos mínimos del alumno

Guardar solo:

- `id`
- `nombreCompleto`
- `cursoAlumno`
- `grupoAlumno`
- `nombrePadres`
- `telefonoContacto` si es imprescindible
- `emailContacto` si es imprescindible
- `menorDeEdad`

No guardar en el MVP salvo necesidad justificada:

- domicilio
- datos médicos
- seguridad social
- nacionalidad
- información familiar ampliada
- tutores múltiples separados en muchas columnas
- datos históricos de matrícula no necesarios

## Datos del expediente

- `id`
- `numeroExpediente`
- `alumnoId`
- `estado`
- `fechaConocimientoHechos`
- `fechaApertura`
- `fechaHechos`
- `hechos`
- `instructorId`
- `conductaTipificada`
- `diasExpulsionCautelar`
- `diasSuspension`
- `tipoCorreccion`
- `calificacionHechos`
- `propuesta`
- `audienciaCelebrada`
- `fechaAudiencia`
- `comunicadoInspeccionInicioAt`
- `comunicadoInspeccionResolucionAt`
- `acuerdoConsejoEscolarAt`
- `resultadoConsejoEscolar`
- `recursoInformado`
- `observacionesInternas`
- `createdAt`
- `updatedAt`
- `closedAt`

## Campos derivados para plantillas

No hace falta guardar todos en base de datos. Algunos se pueden derivar en el momento de generar el documento:

- `diaHechos`
- `mesHechos`
- `diaConsejoEscolar`
- `mesConsejoEscolar`
- `fechaHoraCita`

## Modelo simplificado de tablas

### users

- `id`
- `email`
- `passwordHash`
- `role`
- `mfaEnabled`
- `active`
- `createdAt`

### alumnos

- `id`
- `nombreCompleto`
- `cursoAlumno`
- `grupoAlumno`
- `nombrePadres`
- `telefonoContacto`
- `emailContacto`
- `createdAt`
- `updatedAt`

### expedientes

- `id`
- `numeroExpediente`
- `alumnoId`
- `estado`
- `fechaConocimientoHechos`
- `fechaApertura`
- `fechaHechos`
- `hechos`
- `conductaTipificada`
- `calificacionHechos`
- `propuesta`
- `diasExpulsionCautelar`
- `diasSuspension`
- `tipoCorreccion`
- `instructorUserId`
- `audienciaCelebrada`
- `fechaAudiencia`
- `comunicadoInspeccionInicioAt`
- `comunicadoInspeccionResolucionAt`
- `acuerdoConsejoEscolarAt`
- `resultadoConsejoEscolar`
- `recursoInformado`
- `observacionesInternas`
- `createdAt`
- `updatedAt`
- `closedAt`

### documentos_generados

- `id`
- `expedienteId`
- `tipoPlantilla`
- `templateVersion`
- `storagePath`
- `generatedByUserId`
- `generatedAt`

### auditoria

- `id`
- `userId`
- `entityType`
- `entityId`
- `action`
- `ip`
- `userAgent`
- `createdAt`

## Estados del expediente

- `borrador`
- `iniciado`
- `notificado_inicio`
- `comunicado_inspeccion`
- `medidas_provisionales`
- `en_instruccion`
- `pliego_cargos`
- `audiencia`
- `propuesta_resolucion`
- `elevado_consejo_escolar`
- `resuelto`
- `notificado_resolucion`
- `cerrado`

## Pantallas del MVP

### Login

- Email
- Contraseña
- Segundo factor

### Inicio

- Expedientes recientes
- Accesos rápidos
- Alertas de estado

### Alumnos

- Buscador
- Alta
- Ficha mínima

### Expedientes

- Listado
- Filtros por estado, curso, grupo, instructor
- Crear expediente

### Ficha de expediente

- Resumen
- Datos del alumno
- Hechos
- Tipificación de la conducta
- Fases
- Documentos generados
- Cronología
- Plazos

### Generación de documentos

- Selección de plantilla
- Vista de campos a completar
- Generar `.docx`

### Administración

- Usuarios
- Roles
- Plantillas

## Reglas para el generador de plantillas

- Detectar marcadores `<<...>>` aunque Word los parta en varios fragmentos.
- Si el nombre del marcador está en mayúsculas, transformar el valor a mayúsculas.
- Si el marcador está en negrita, mantener la negrita.
- Mantener el resto del estilo del texto.
- Permitir alias internos mientras existan plantillas antiguas.

## Ajustes normativos obligatorios en el flujo

### Competencia sancionadora

- La resolución debe quedar vinculada al Consejo Escolar.
- La app no debe permitir cerrar como resuelto un expediente sin registrar acuerdo del Consejo Escolar cuando proceda.

### Instructor

- El instructor debe ser un profesor del centro designado por Dirección.
- Debe quedar registro de designación.

### Recusación

- Debe existir un campo o evento para registrar recusación del instructor y su resolución por Dirección.
- No hace falta un módulo complejo en el MVP, pero sí trazabilidad.

### Medidas provisionales

- Solo pueden adoptarse excepcionalmente.
- El sistema debe limitar la suspensión cautelar a un máximo de 5 días.
- Debe quedar constancia de su comunicación al Consejo Escolar.

### Audiencia

- La app debe obligar a registrar el trámite de audiencia antes de la propuesta final.
- Si el alumno es menor de edad, debe incluir comunicación a padres o representantes legales.

### Comunicación a Inspección

- Debe existir registro obligatorio del inicio del procedimiento.
- Debe existir trazabilidad de las comunicaciones posteriores hasta la resolución.

### Plazos

- `fechaConocimientoHechos` es obligatoria porque dispara el plazo de 10 días del artículo 55.1.
- La resolución debe alertar si se supera 1 mes desde el inicio.

### Catálogo de correcciones

La app debe limitar las correcciones gravemente perjudiciales del artículo 53 a valores cerrados:

- `tareas_reparadoras`
- `suspension_extraescolares`
- `cambio_grupo`
- `suspension_determinadas_clases`
- `suspension_asistencia_centro`
- `cambio_centro`

### Trabajo académico durante suspensión

- Si la corrección es suspensión de clases o suspensión de asistencia al centro, debe existir un campo para consignar los deberes o trabajos a realizar.

## Seguridad

### Autenticación

- Contraseñas con hash fuerte.
- MFA obligatorio.
- Política de sesión corta.
- Bloqueo tras varios intentos fallidos.

### Autorización

- Control de acceso por rol.
- Comprobación de permisos en servidor, no solo en interfaz.

### Protección de datos

- HTTPS obligatorio.
- Base de datos cifrada o disco cifrado.
- Copias de seguridad cifradas.
- Secretos fuera del código.
- Logs sin datos sensibles.

### Superficie pública

- Rate limiting.
- Cabeceras seguras.
- CSRF en formularios.
- Validación estricta de entrada.
- Sanitización de texto libre.
- No exponer rutas reales de almacenamiento.

### Auditoría

- Registrar accesos, descargas y cambios.
- Identificar usuario, fecha y acción.
- Registrar específicamente:
  - designación de instructor
  - adopción y revocación de medidas provisionales
  - audiencia
  - propuesta al Consejo Escolar
  - acuerdo del Consejo Escolar
  - notificaciones

## Arquitectura recomendada

## Opción recomendada

- `Flask` para aplicación web.
- `SQLite` para base de datos inicial.
- Almacenamiento privado para plantillas y documentos generados.
- Despliegue detrás de proxy inverso seguro.

## Motivo

- Menor complejidad operativa.
- Muy adecuado para una herramienta administrativa interna con pocos usuarios concurrentes.
- Fácil de desplegar en VPS.
- Permite construir el generador documental en el servidor sin depender de un stack JavaScript.

## Importación inicial desde Excel

- Crear un importador único.
- Mapear solo columnas necesarias.
- Revisar antes de confirmar importación.
- No volver a depender del Excel como fuente principal.

## Impacto de la normativa en las plantillas actuales

- Las plantillas existentes encajan bastante bien con el esquema del Real Decreto:
  - inicio de expediente
  - comunicación a Inspección
  - medidas provisionales
  - citación
  - pliego de cargos
  - vista y audiencia
  - propuesta de resolución
  - acuerdo/notificación final
- Falta garantizar en la app, más que en las plantillas, estos extremos:
  - registro de fecha de conocimiento de los hechos
  - control de plazo de 10 días, 7 días y 1 mes
  - registro del acuerdo del Consejo Escolar
  - registro de recusación
  - trabajos académicos durante suspensión

## Orden recomendado de desarrollo

1. Esquema de base de datos mínimo.
2. Autenticación y roles.
3. CRUD de alumnos.
4. CRUD de expedientes con hitos y plazos normativos.
5. Generador de plantillas `.docx`.
6. Auditoría.
7. Panel de administración.
8. Reglas de validación procedimental.

## Decisiones abiertas

- Si `nombrePadres` será un único texto o dos campos separados.
- Si el número de expediente será manual o automático.
- Si se guardarán PDFs además de `.docx`.
- Si habrá cierre con firma digital en una fase posterior.
