# Copia de documentos a Teams

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

Este procedimiento es manual. No instala ninguna tarea periodica ni modifica
la app del VPS o el flujo de Power Automate. La sincronizacion automatica al
cerrar expedientes sigue pendiente.

Pruebas sin datos reales:

```sh
python3 -m unittest discover -s tests -p test_teams_sync.py
```
