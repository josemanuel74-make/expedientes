# Copia automatica de documentos a Teams

## Funcionamiento automatico

La tarea de macOS `es.edumelilla.expedientes-teams-sync` revisa el VPS cada
5 minutos y al iniciar sesion. Revisa los expedientes abiertos y cerrados que
tengan documentos, sin limitarse por fecha de cierre. Compara los registros
y las huellas SHA-256 del contenido, por lo que tambien detecta un cambio
en un archivo con el mismo nombre y sin una nueva fecha en la base de datos.
Copia las ultimas versiones de los DOCX y los PDF firmados a la carpeta ya
creada del expediente para el curso configurado.
Tambien incluye los PDF del 07 (Vista y Audiencia) y del 11 (Notificacion
a familias) aportados con la firma de la familia. Su huella provoca una
nueva copia, aunque el expediente estuviera cerrado antes de activar la tarea.

OneDrive completa la subida a Teams. El Mac debe estar encendido, con la
sesion iniciada y OneDrive conectado. Si esta apagado o sin red, el cambio
queda pendiente y se recoge en una revision posterior. No depende de tener
abierta la app web o Codex. El VPS se consulta en modo solo lectura.

Los fallos de conexion, carpetas todavia no disponibles o conflictos de
archivos se reintentan en las siguientes revisiones y quedan registrados.
Se guarda la huella de cada archivo copiado. Si el origen cambia y el destino
conserva la huella de la ultima copia gestionada, el destino se actualiza
mediante un archivo temporal verificado y una sustitucion atomica. Si el
destino se modifico manualmente, o no hay una huella previa que permita
identificarlo, el conflicto requiere revision manual y no se sobrescribe.
La copia no borra archivos de otras versiones ni cambia permisos.

Instalacion desde la raiz del proyecto (macOS):

```sh
python3 tools/install_teams_sync.py \
  --teams-root "/ruta/a/002 - Expedientes Disciplinarios 26 - 27" \
  --identity "/ruta/a/la/clave/SSH"
```

El instalador conserva el estado si ya existia. El estado, fechas de revision
y errores estan en `~/Library/Application Support/ExpedientesTeamsSync/`:

- `state.json`: fecha de activacion informativa, huellas de documentos y archivos copiados, y errores por expediente.
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
identico, no vuelve a copiarlo. El comando manual no usa el estado de la tarea:
si existe uno diferente con el mismo nombre, se detiene antes de copiar y
requiere revisar el conflicto. No borra archivos
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
