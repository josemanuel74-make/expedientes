# Copia automatica de documentos a Teams

## Funcionamiento automatico

La tarea de macOS `es.edumelilla.expedientes-teams-sync` revisa el VPS cada
5 minutos y al iniciar sesion. Detecta expedientes con estado `cerrado` y
fecha de cierre posterior a su activacion. En la app, ese cierre se produce
al firmar el documento 12. Copia las ultimas versiones de los DOCX y los
PDF firmados a la carpeta ya creada del expediente para el curso configurado.

OneDrive completa la subida a Teams. El Mac debe estar encendido, con la
sesion iniciada y OneDrive conectado. Si esta apagado o sin red, el cierre
queda pendiente y se recoge en una revision posterior. No depende de tener
abierta la app web o Codex. El VPS se consulta en modo solo lectura.

Los fallos de conexion, carpetas todavia no disponibles o conflictos de
archivos se reintentan en las siguientes revisiones y quedan registrados.
Un conflicto con un archivo diferente requiere revision manual; no se
sobrescribe automaticamente. La copia no borra archivos ni cambia permisos.

Instalacion desde la raiz del proyecto (macOS):

```sh
python3 tools/install_teams_sync.py \
  --teams-root "/ruta/a/002 - Expedientes Disciplinarios 26 - 27" \
  --identity "/ruta/a/la/clave/SSH"
```

El instalador conserva el estado si ya existia. El estado, fechas de revision
y errores estan en `~/Library/Application Support/ExpedientesTeamsSync/`:

- `state.json`: inicio de seguimiento, huellas copiadas y errores por expediente.
- `worker.log`: revisiones y copias verificadas en la carpeta de OneDrive.
- `worker-error.log`: errores de ejecucion o conexion.

El instalador guarda en esa carpeta privada (permisos 700) una copia de la
identidad SSH existente, con permisos 600. Evita que SSH en segundo plano se
quede esperando acceso a Descargas. No crea claves nuevas ni cambia los
permisos del VPS. La clave no se incorpora al repositorio ni a los registros.

`copied_to_onedrive_at` confirma la copia local, no la subida a la nube.
OneDrive es quien completa esa subida. Al cambiar de curso hay que actualizar
la ruta de la biblioteca en la tarea; no se elige una carpeta por aproximacion.

Consulta y desactivacion:

```sh
launchctl print gui/$(id -u)/es.edumelilla.expedientes-teams-sync
launchctl bootout gui/$(id -u)/es.edumelilla.expedientes-teams-sync
```

Para desactivarla tambien en inicios de sesion posteriores, retirar su plist
de `~/Library/LaunchAgents/`. No afecta a las copias ya realizadas.

## Copia Manual

`tools/sync_teams.py` descarga las ultimas versiones de los DOCX y sus PDF
firmados desde el VPS y los copia a la carpeta existente del expediente
en la biblioteca de Teams sincronizada por OneDrive en este ordenador.

Ejecutar desde la raiz del proyecto:

```sh
python3 tools/sync_teams.py --case 03 \
  --teams-root "/ruta/a/002 - Expedientes Disciplinarios 26 - 27" \
  --identity "/ruta/a/la/clave/SSH" --dry-run
```

Quitar `--dry-run` para copiar. Debe existir una unica carpeta con el prefijo
`03 - ` dentro de la carpeta indicada. No se crean carpetas nuevas.

La copia verifica SHA-256 de todos los archivos. Si ya existe un archivo
identico, no vuelve a copiarlo. Si existe uno diferente con el mismo nombre,
se detiene antes de copiar y requiere revisar el conflicto. No borra archivos
ni modifica permisos. No copia versiones anteriores ni PDF sin firmar.

OneDrive realiza la subida a SharePoint/Teams despues de la copia local;
el resultado de la herramienta no confirma por si solo la subida a la nube.
Hay que comprobar el resultado en la biblioteca de Teams.

El instalador compila el lector `coordinated_sha256.swift` con las herramientas
de desarrollo de Apple. Se usa para verificar archivos que OneDrive ha dejado
solo en la nube, mediante NSFileCoordinator. No cambia la configuracion de
OneDrive ni sus permisos.

La herramienta manual no instala tareas. La automatizacion se activa con
el instalador anterior y no modifica la app del VPS o Power Automate.

Pruebas sin datos reales:

```sh
python3 -m unittest discover -s tests -p 'test_teams*.py'
```
