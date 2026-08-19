# Perfumería Burbujita

Aplicación web para mostrar y administrar el catálogo de una perfumería. Incluye una tienda pública, carrito de compras y consultas por WhatsApp, además de un panel privado para gestionar productos, categorías y promociones.

## Funcionalidades

- Catálogo público con productos, precios, descuentos e imágenes.
- Galería de imágenes y vista ampliada para cada producto.
- Categorías y subcategorías para filtrar el catálogo.
- Carrito persistente en el navegador mediante `localStorage`.
- Generación de pedidos y consultas a través de WhatsApp.
- Panel de administración con autenticación y protección CSRF.
- Alta, edición y eliminación de productos y categorías.
- Campañas promocionales con fecha de expiración.
- Descuento global temporal para toda la tienda.
- Base de datos SQLite con migraciones compatibles con versiones anteriores.

## Tecnologías

- Python 3.10 o superior
- Flask
- SQLite
- HTML, JavaScript y Tailwind CSS mediante CDN

## Requisitos

- Python instalado.
- Un navegador web actualizado.
- Un número de WhatsApp comercial para recibir consultas y pedidos.

## Instalación

1. Cloná el repositorio y entrá en la carpeta del proyecto:

   ```bash
   git clone URL_DEL_REPOSITORIO
   cd Perfumeria1
   ```

2. Creá y activá un entorno virtual.

   En Windows PowerShell:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   En macOS o Linux:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Instalá Flask:

   ```bash
   python -m pip install Flask
   ```

4. Iniciá la aplicación:

   ```bash
   python app.py
   ```

5. Abrí [http://127.0.0.1:5000](http://127.0.0.1:5000) en el navegador.

La base de datos `perfumeria.db` y la carpeta `static/uploads/` se crean o actualizan automáticamente al iniciar la aplicación.

## Acceso al panel

El panel de administración está disponible en `/login`.

Por defecto, las credenciales iniciales son:

```text
Usuario: admin
Contraseña: Burbujita3026!
```

Cambialas antes de publicar la aplicación. Podés definir otras credenciales mediante variables de entorno:

```powershell
$env:BURBUJITA_ADMIN_USER="tu_usuario"
$env:BURBUJITA_ADMIN_PASSWORD="una_contrasena_segura"
$env:FLASK_SECRET_KEY="una_clave_larga_y_aleatoria"
python app.py
```

Estas variables sólo se usan al crear el usuario inicial. Si el usuario `admin` ya existe en `perfumeria.db`, cambiar las variables no modifica sus credenciales automáticamente.

## Configuración de WhatsApp

Editá la constante `NUMERO_WHATSAPP` en `templeates/index.html` y reemplazá su valor por el número comercial en formato internacional, sin `+`, espacios ni guiones.

Ejemplo:

```javascript
const NUMERO_WHATSAPP = '5491123456789';
```

## API principal

| Método | Ruta | Acceso | Descripción |
| --- | --- | --- | --- |
| `GET` | `/api/productos` | Público | Lista los productos del catálogo. |
| `POST` | `/api/productos` | Administrador | Crea un producto con sus imágenes. |
| `PUT` | `/api/productos/<id>` | Administrador | Actualiza un producto. |
| `DELETE` | `/api/productos/<id>` | Administrador | Elimina un producto. |
| `GET` | `/api/categorias` | Público | Lista categorías y subcategorías. |
| `POST/PUT/DELETE` | `/api/categorias...` | Administrador | Gestiona categorías. |
| `GET` | `/api/promocion-activa` | Público | Devuelve la promoción vigente. |
| `GET/PUT` | `/api/configuracion-promocion` | Administrador | Consulta o actualiza campañas. |

Las operaciones que modifican datos requieren una sesión de administrador y un token CSRF válido.

## Estructura del proyecto

```text
.
├── app.py                  # Servidor Flask, rutas y acceso a SQLite
├── perfumeria.db           # Base de datos local
├── templeates/             # Plantillas HTML de la tienda y el panel
├── static/                 # Archivos estáticos
│   └── uploads/            # Imágenes cargadas desde el panel
└── perfumeria_web/         # Recursos adicionales del proyecto
```

## Publicación

Antes de desplegar:

- Configurá `FLASK_SECRET_KEY` con una clave persistente y segura.
- Cambiá las credenciales iniciales del administrador.
- No publiques credenciales, archivos `.env` ni copias de la base de datos con información sensible.
- Usá un servidor WSGI para producción, como Waitress o Gunicorn.
- Configurá HTTPS para proteger las sesiones y las credenciales.
- Revisá el número de WhatsApp y el contenido de los términos y condiciones.

## Licencia

Este proyecto no tiene una licencia definida todavía. Agregá un archivo `LICENSE` antes de distribuirlo públicamente.
