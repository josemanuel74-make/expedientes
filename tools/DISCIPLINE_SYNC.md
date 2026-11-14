# Partes de Fenicia

El servidor consulta una copia privada normalizada del Excel del curso, no el OneDrive directamente. Solo administra este asistente el rol admin. No se envían datos a una API de inteligencia artificial; la redacción es determinista, con fechas y referencias al parte original.

Instalar tools/requirements-discipline-sync.txt en un Python permanente del Mac. Ejecutar tools/install_discipline_sync.py con --excel, --school-year (por ejemplo 2026-2027) y --identity (clave SSH existente del servidor). Desplegar antes disciplinarios/discipline.py en el VPS.

El instalador publica primero la copia y registra es.edumelilla.expedientes-discipline-reports en LaunchAgents, con intervalo de cinco minutos. Guarda scripts y estado en Library/Application Support/ExpedientesTeamsSync. No modifica el Excel. Requiere el Mac encendido con sesión y conectividad. Revisar discipline.log y discipline-error.log si falta la actualización.

En el VPS, instance/discipline_reports.json se reemplaza atómicamente con permisos 600. DISCIPLINE_REPORTS_PATH permite configurar otra ubicación. No publicar este fichero ni incluirlo en Git. Se rechazan homónimos ambiguos, grupos distintos y selecciones de partes de otro alumno. Al cambiar de curso, reinstalar indicando el nuevo Excel y curso.
