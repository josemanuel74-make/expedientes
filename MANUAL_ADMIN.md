# Manual corto · Admin

## Acceso

1. Entra en la web de la aplicación.
2. Escribe tu correo autorizado.
3. Solicita el código de acceso.
4. Revisa tu correo.
5. Introduce el código y entra.

## Qué puede hacer un admin

- crear expedientes
- editar expedientes
- gestionar alumnado
- generar cualquier documento
- firmar los documentos que correspondan a Dirección
- descargar `DOCX`, `PDF firmados` y `ZIP`
- gestionar administradores

## Flujo recomendado

1. Ir a `Alumnos` y comprobar que el alumno existe.
2. Si no existe, importarlo o darlo de alta.
3. Ir a `Expedientes` y crear uno nuevo.
4. Asignar instructor.
5. Generar los documentos que correspondan al tramo de admin.
6. Revisar si hay firmas pendientes.
7. Descargar el expediente cuando haga falta.

## Documentos que suele hacer Dirección / admin

- `01`
- `02`
- `04`
- `10`
- `11`
- `12`

El admin puede generar cualquier documento, pero ese es el reparto operativo actual.

## Crear un expediente

1. Entra en `Expedientes`.
2. Pulsa `Nuevo expediente`.
3. Busca al alumno.
4. Introduce los datos básicos.
5. Selecciona instructor.
6. Guarda.

## Generar un documento

1. Abre el expediente.
2. En `Continuar`, elige la plantilla.
3. Rellena solo los campos que pide ese documento.
4. Guarda y genera el `DOCX`.

Si un dato ya existe en el expediente, la app intenta reutilizarlo.

## Firmar un documento

1. Abre el expediente.
2. En `Documentos generados`, pulsa `Firmar PDF`.
3. Se abrirá el flujo de AutoFirma.
4. Cuando termine, vuelve al expediente.
5. El documento firmado aparecerá como `Firmado`.

## Versiones

- La app puede generar varias versiones del mismo documento: `v01`, `v02`, etc.
- En la tabla principal se muestra la versión actual.
- Las versiones anteriores quedan dentro de `Ver versiones anteriores`.

## Descargas

Desde el expediente puedes descargar:

- `DOCX`
- `PDF firmado`
- `ZIP`

La app registra estas descargas en la cronología.

## Qué no debes hacer

- no borrar documentos si no estás seguro
- no regenerar una versión firmada salvo que realmente haya que crear una nueva versión
- no compartir códigos de acceso
- no dejar la sesión abierta en un equipo compartido

## Cierre de sesión

- la sesión caduca por inactividad
- además tiene una duración máxima
- si la app te saca, vuelve a pedir un código

## Incidencias habituales

### No llega el código

- revisa spam
- vuelve a pedirlo
- confirma que el correo está autorizado

### No deja firmar

- comprueba que el documento te corresponde
- comprueba que es la versión actual
- revisa que AutoFirma esté operativo

### No aparece una plantilla

- puede estar bloqueada por flujo
- puede no corresponder a tu rol

## Revisión final antes de cerrar un expediente

- comprobar que los documentos obligatorios están generados
- comprobar que los firmables están firmados
- revisar la cronología
- descargar el `ZIP` si hace falta archivo externo
