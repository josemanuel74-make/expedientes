# Preparación del VPS

Este proyecto está pensado para desplegarse en un VPS Linux con:

- `Ubuntu 24.04 LTS` o `Ubuntu 22.04 LTS`
- `Python 3.11+`
- `nginx`
- `gunicorn`
- `systemd`

## 1. Requisitos mínimos

Servidor recomendado:

- `1 vCPU`
- `2 GB RAM`
- `20 GB SSD`

Puertos:

- `22` para SSH
- `80` para HTTP
- `443` para HTTPS

## 2. Usuario y ruta

Usa un usuario de sistema dedicado, por ejemplo:

- usuario: `expedientes`
- ruta de aplicación: `/opt/expedientes`

## 3. Paquetes del sistema

En el VPS:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
```

## 4. Estructura prevista

Ruta final recomendada:

```text
/opt/expedientes
```

Con esta estructura:

```text
/opt/expedientes/.venv
/opt/expedientes/.env
/opt/expedientes/instance/
/opt/expedientes/generated_docs/
/opt/expedientes/templates/
/opt/expedientes/static/
/opt/expedientes/disciplinarios/
```

## 5. Variables de entorno

Copia la plantilla:

```bash
cp deploy/.env.production.example .env
```

Y rellena:

- `SECRET_KEY`
- `APP_BASE_URL`
- `MAIL_HOST`
- `MAIL_PORT`
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_FROM`
- `MAIL_USE_TLS`

## 6. Archivos que no deben ir a Git

Se gestionan directamente en el VPS:

- `.env`
- `instance/disciplinarios.sqlite3`
- `generated_docs/`
- `RegAlum (1).xls`
- `todosProfesores.xlsx`

## 7. Ficheros que tendrás que copiar al VPS

Además del repo, tendrás que subir manualmente:

- `RegAlum (1).xls`
- `todosProfesores.xlsx`

Sin esos dos Excel la app seguirá arrancando, pero:

- no podrás importar alumnado real
- no tendrás directorio real de instructores

## 8. Siguiente paso

Cuando el VPS esté listo, el orden correcto será:

1. clonar repo
2. crear `.venv`
3. instalar dependencias
4. crear `.env`
5. copiar los dos Excel
6. arrancar `gunicorn`
7. configurar `systemd`
8. configurar `nginx`
9. emitir HTTPS
