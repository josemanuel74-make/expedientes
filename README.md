# Expedientes disciplinarios

Aplicación web para gestionar expedientes disciplinarios del `IES Leopoldo Queipo` con:

- `Flask`
- `SQLite`
- plantillas `.docx`
- acceso por correo con código de un solo uso
- roles de `admin` e `instructor`

## Estado actual

La aplicación ya incluye:

- login por código enviado por correo
- administradores por whitelist
- instructores tomados del Excel `todosProfesores.xlsx`
- aviso por correo al nombrar instructor
- visibilidad restringida: el instructor solo ve sus expedientes
- importación de alumnado desde `RegAlum (1).xls`
- generación de documentos Word desde plantillas
- control básico del flujo 01-12

## Arranque local

1. Crea y activa el entorno virtual si no lo tienes ya:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Crea tu fichero de entorno:

```bash
cp .env.example .env
```

3. Arranca la aplicación:

```bash
source .venv/bin/activate
python app.py
```

4. Abre:

- [http://127.0.0.1:5000/login](http://127.0.0.1:5000/login)

## Acceso local

Administradores iniciales:

- `josemanuel.rodriguez@edumelilla.es`
- `carlos.moya@edumelilla.es`

En local, si `MAIL_HOST` está vacío, los correos no se envían de verdad:

- el código de acceso aparece impreso en la terminal donde has arrancado la app

## Variables de entorno

Estas variables se leen desde `.env` si existe:

- `SECRET_KEY`
- `APP_BASE_URL`
- `MAIL_HOST`
- `MAIL_PORT`
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_FROM`
- `MAIL_USE_TLS`

### Configuración mínima local

```env
SECRET_KEY=una-clave-larga-y-aleatoria
APP_BASE_URL=http://127.0.0.1:5000
MAIL_HOST=
MAIL_PORT=587
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_FROM=
MAIL_USE_TLS=true
```

### Configuración mínima para VPS

```env
SECRET_KEY=una-clave-larga-y-aleatoria
APP_BASE_URL=https://tu-dominio-o-ip
MAIL_HOST=smtp.tu-servidor
MAIL_PORT=587
MAIL_USERNAME=tu-cuenta-smtp
MAIL_PASSWORD=tu-password-smtp
MAIL_FROM=no-reply@tu-dominio
MAIL_USE_TLS=true
```

## Despliegue con gunicorn

Con el entorno activado:

```bash
gunicorn --bind 127.0.0.1:5000 wsgi:app
```

Para producción, la idea correcta es:

1. `gunicorn` escuchando en local
2. `nginx` delante
3. HTTPS en `nginx`
4. `.env` con SMTP real

## Notas de producción

- no subas `.env` al repositorio
- no expongas directamente `generated_docs/` ni `instance/`
- haz copia periódica de `instance/disciplinarios.sqlite3`
- limita acceso al servidor si es posible por IP o VPN

## Siguiente bloque recomendado

- `.env` real para VPS
- configuración SMTP real
- servicio `systemd` para `gunicorn`
- configuración `nginx`
- backup automático de base de datos y documentos

## Preparación del VPS

He dejado plantillas y guía base en:

- [deploy/PRODUCCION.md](/Users/jose/Library/CloudStorage/OneDrive-DirecciónProvincialdeMelilla/Proyectos/expedientes disciplinarios/deploy/PRODUCCION.md)
- [deploy/.env.production.example](/Users/jose/Library/CloudStorage/OneDrive-DirecciónProvincialdeMelilla/Proyectos/expedientes disciplinarios/deploy/.env.production.example)
- [deploy/expedientes.service](/Users/jose/Library/CloudStorage/OneDrive-DirecciónProvincialdeMelilla/Proyectos/expedientes disciplinarios/deploy/expedientes.service)
- [deploy/nginx.expedientes.conf](/Users/jose/Library/CloudStorage/OneDrive-DirecciónProvincialdeMelilla/Proyectos/expedientes disciplinarios/deploy/nginx.expedientes.conf)

## Manuales de uso

- [MANUAL_ADMIN.md](/Users/jose/Library/CloudStorage/OneDrive-DirecciónProvincialdeMelilla/Proyectos/expedientes disciplinarios/MANUAL_ADMIN.md)
- [MANUAL_INSTRUCTOR.md](/Users/jose/Library/CloudStorage/OneDrive-DirecciónProvincialdeMelilla/Proyectos/expedientes disciplinarios/MANUAL_INSTRUCTOR.md)
