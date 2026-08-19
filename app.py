"""Backend de Perfumería Burbujita.

Las migraciones de ``init_db`` son idempotentes: actualizan la base SQLite
existente y conservan los productos cargados anteriormente.
"""

from datetime import datetime, timedelta
from functools import wraps
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
from uuid import uuid4

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / 'perfumeria.db'
UPLOAD_FOLDER = BASE_DIR / 'static' / 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
DEFAULT_ADMIN_USERNAME = os.environ.get('BURBUJITA_ADMIN_USER', 'admin')
DEFAULT_ADMIN_PASSWORD = os.environ.get('BURBUJITA_ADMIN_PASSWORD', 'Burbujita2026!')

app = Flask(__name__, template_folder='templeates', static_folder='static')
app.config.update(
    # En producción configurá FLASK_SECRET_KEY para conservar sesiones tras reinicios.
    # Sin ella se genera una clave segura efímera, que invalida sesiones al reiniciar.
    SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or secrets.token_urlsafe(48),
    UPLOAD_FOLDER=str(UPLOAD_FOLDER),
    MAX_CONTENT_LENGTH=20 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('FLASK_ENV') == 'production',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


def conexion():
    """Crea una conexión con claves foráneas activadas."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def columnas_de(tabla):
    with conexion() as conn:
        return {fila['name'] for fila in conn.execute(f'PRAGMA table_info({tabla})')}


def init_db():
    """Crea o migra el esquema sin borrar datos existentes.

    Las promociones históricas (``promocion = 1``) se traducen a un 10 % de
    descuento, ya que el antiguo campo no guardaba un porcentaje.
    """
    with conexion() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL COLLATE NOCASE UNIQUE,
                parent_id INTEGER,
                FOREIGN KEY (parent_id) REFERENCES categorias(id)
                    ON DELETE RESTRICT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                precio REAL NOT NULL,
                imagen TEXT NOT NULL,
                especificacion TEXT DEFAULT '',
                descuento_porcentaje INTEGER NOT NULL DEFAULT 0
                    CHECK (descuento_porcentaje BETWEEN 0 AND 100),
                categoria_id INTEGER,
                FOREIGN KEY (categoria_id) REFERENCES categorias(id)
                    ON DELETE SET NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS imagenes_producto (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                producto_id INTEGER NOT NULL,
                ruta_imagen TEXT NOT NULL,
                FOREIGN KEY (producto_id) REFERENCES productos(id)
                    ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS configuracion_promocion (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                texto_promocion TEXT NOT NULL DEFAULT '',
                fecha_expiracion TEXT,
                activa INTEGER NOT NULL DEFAULT 0 CHECK (activa IN (0, 1)),
                descuento_global_porcentaje INTEGER NOT NULL DEFAULT 0,
                fecha_fin_descuento TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios_admin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO configuracion_promocion
                (id, texto_promocion, fecha_expiracion, activa)
            VALUES (1, '', NULL, 0)
        ''')
        config_columnas = {fila['name'] for fila in cursor.execute('PRAGMA table_info(configuracion_promocion)')}
        if 'descuento_global_porcentaje' not in config_columnas:
            cursor.execute('ALTER TABLE configuracion_promocion ADD COLUMN descuento_global_porcentaje INTEGER NOT NULL DEFAULT 0')
        if 'fecha_fin_descuento' not in config_columnas:
            cursor.execute('ALTER TABLE configuracion_promocion ADD COLUMN fecha_fin_descuento TEXT')
        cursor.execute('''
            INSERT OR IGNORE INTO usuarios_admin (usuario, password_hash)
            VALUES (?, ?)
        ''', (DEFAULT_ADMIN_USERNAME, generate_password_hash(DEFAULT_ADMIN_PASSWORD)))

        # Compatibilidad con las versiones anteriores del proyecto.
        columnas = {fila['name'] for fila in cursor.execute('PRAGMA table_info(productos)')}
        if 'especificacion' not in columnas:
            cursor.execute("ALTER TABLE productos ADD COLUMN especificacion TEXT DEFAULT ''")
        if 'descuento_porcentaje' not in columnas:
            cursor.execute('ALTER TABLE productos ADD COLUMN descuento_porcentaje INTEGER NOT NULL DEFAULT 0')
            if 'promocion' in columnas:
                cursor.execute('UPDATE productos SET descuento_porcentaje = 10 WHERE promocion = 1')
        if 'categoria_id' not in columnas:
            cursor.execute('ALTER TABLE productos ADD COLUMN categoria_id INTEGER')

        # Pasa las categorías de texto de versiones anteriores a la tabla nueva.
        if 'categoria' in columnas:
            filas = cursor.execute('''
                SELECT DISTINCT trim(categoria) AS nombre
                FROM productos
                WHERE categoria IS NOT NULL AND trim(categoria) <> ''
            ''').fetchall()
            for fila in filas:
                cursor.execute('INSERT OR IGNORE INTO categorias (nombre) VALUES (?)', (fila['nombre'],))
            cursor.execute('''
                UPDATE productos
                SET categoria_id = (
                    SELECT id FROM categorias WHERE categorias.nombre = trim(productos.categoria)
                )
                WHERE categoria_id IS NULL AND categoria IS NOT NULL AND trim(categoria) <> ''
            ''')
        # Convierte la imagen única histórica en la primera imagen de galería.
        cursor.execute('''
            INSERT INTO imagenes_producto (producto_id, ruta_imagen)
            SELECT p.id, p.imagen
            FROM productos p
            WHERE NOT EXISTS (
                SELECT 1 FROM imagenes_producto i WHERE i.producto_id = p.id
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_imagenes_producto_producto ON imagenes_producto(producto_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_productos_categoria ON productos(categoria_id)')


init_db()


def serializar_producto(fila, imagenes, descuento_global_porcentaje=0):
    return {
        'id': fila['id'],
        'nombre': fila['nombre'],
        'precio': fila['precio'],
        'imagen': fila['imagen'],
        'imagenes': imagenes or [fila['imagen']],
        'especificacion': fila['especificacion'] or '',
        'descuento_porcentaje': fila['descuento_porcentaje'] or 0,
        'descuento_global_porcentaje': descuento_global_porcentaje,
        'categoria_id': fila['categoria_id'],
        'categoria': fila['categoria'] or '',
    }


def obtener_datos_producto():
    nombre = request.form.get('nombre', '').strip()
    especificacion = request.form.get('especificacion', '').strip()
    precio_texto = request.form.get('precio', '').strip()
    categoria_id = request.form.get('categoria_id', '').strip()
    descuento_texto = request.form.get('descuento_porcentaje', '0').strip()
    if not nombre or not precio_texto:
        return None, ('Nombre y precio son obligatorios.', 400)
    try:
        precio = float(precio_texto)
        descuento = int(descuento_texto or 0)
        categoria_id = int(categoria_id) if categoria_id else None
    except ValueError:
        return None, ('El precio, descuento o categoría no son válidos.', 400)
    if precio < 0 or not 0 <= descuento <= 100:
        return None, ('El descuento debe estar entre 0 y 100 y el precio no puede ser negativo.', 400)
    return {
        'nombre': nombre, 'precio': precio, 'especificacion': especificacion,
        'descuento_porcentaje': descuento, 'categoria_id': categoria_id,
    }, None


def guardar_imagen(archivo):
    if not archivo or not archivo.filename:
        return None, 'La imagen es obligatoria.'
    nombre_seguro = secure_filename(archivo.filename)
    extension = nombre_seguro.rsplit('.', 1)[-1].lower() if '.' in nombre_seguro else ''
    if extension not in ALLOWED_EXTENSIONS:
        return None, 'Formato de imagen no permitido.'
    nombre_final = f'{uuid4().hex}.{extension}'
    archivo.save(UPLOAD_FOLDER / nombre_final)
    return f'static/uploads/{nombre_final}', None


def guardar_imagenes(archivos, obligatorias=False):
    """Guarda una lista de imágenes y devuelve las rutas o un error."""
    archivos_validos = [archivo for archivo in archivos if archivo and archivo.filename]
    if obligatorias and not archivos_validos:
        return None, 'Debés seleccionar al menos una imagen.'
    rutas = []
    for archivo in archivos_validos:
        ruta, error = guardar_imagen(archivo)
        if error:
            return None, error
        rutas.append(ruta)
    return rutas, None


def categoria_existe(conn, categoria_id):
    return categoria_id is None or conn.execute(
        'SELECT 1 FROM categorias WHERE id = ?', (categoria_id,)
    ).fetchone() is not None


def token_csrf():
    """Devuelve un token de sesión para proteger todas las escrituras."""
    return session.setdefault('csrf_token', secrets.token_urlsafe(32))


def respuesta_no_autorizada(mensaje, codigo=401):
    if request.path.startswith('/api/'):
        return jsonify({'mensaje': mensaje}), codigo
    return redirect(url_for('login', siguiente=request.url))


def admin_requerido(vista):
    """Exige sesión de administrador y token CSRF en operaciones mutables."""
    @wraps(vista)
    def protegida(*args, **kwargs):
        if not session.get('admin_id'):
            return respuesta_no_autorizada('Iniciá sesión para realizar esta operación.')
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            recibido = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            esperado = session.get('csrf_token', '')
            if not recibido or not esperado or not hmac.compare_digest(recibido, esperado):
                return respuesta_no_autorizada('La sesión expiró. Recargá la página e intentá nuevamente.', 400)
        return vista(*args, **kwargs)
    return protegida


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('admin_id'):
        return redirect(url_for('admin'))
    error = None
    if request.method == 'POST':
        recibido = request.form.get('csrf_token', '')
        esperado = session.get('csrf_token', '')
        if not recibido or not esperado or not hmac.compare_digest(recibido, esperado):
            error = 'La sesión expiró. Recargá la página e intentá nuevamente.'
        else:
            usuario = request.form.get('usuario', '').strip()
            contrasena = request.form.get('contrasena', '')
            with conexion() as conn:
                admin = conn.execute(
                    'SELECT id, usuario, password_hash FROM usuarios_admin WHERE usuario = ?', (usuario,)
                ).fetchone()
            if admin and check_password_hash(admin['password_hash'], contrasena):
                session.clear()
                session['admin_id'] = admin['id']
                session['admin_usuario'] = admin['usuario']
                session['csrf_token'] = secrets.token_urlsafe(32)
                session.permanent = True
                destino = request.form.get('siguiente', '')
                return redirect(destino if destino.startswith('/') and not destino.startswith('//') else url_for('admin'))
            error = 'Usuario o contraseña incorrectos.'
    return render_template('login.html', csrf_token=token_csrf(), error=error, siguiente=request.args.get('siguiente', ''))


@app.route('/logout', methods=['POST'])
@admin_requerido
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/admin')
@admin_requerido
def admin():
    return render_template('admin.html', csrf_token=token_csrf(), admin_usuario=session.get('admin_usuario', 'Admin'))


@app.route('/api/productos', methods=['GET'])
def obtener_productos():
    with conexion() as conn:
        filas = conn.execute('''
            SELECT p.id, p.nombre, p.precio, p.imagen, p.especificacion,
                   p.descuento_porcentaje, p.categoria_id, c.nombre AS categoria
            FROM productos p
            LEFT JOIN categorias c ON c.id = p.categoria_id
            ORDER BY p.id DESC
        ''').fetchall()
        imagenes_por_producto = {}
        for imagen in conn.execute('SELECT producto_id, ruta_imagen FROM imagenes_producto ORDER BY id'):
            imagenes_por_producto.setdefault(imagen['producto_id'], []).append(imagen['ruta_imagen'])
        config = conn.execute('''
            SELECT descuento_global_porcentaje, fecha_fin_descuento
            FROM configuracion_promocion WHERE id=1
        ''').fetchone()
        descuento_global = descuento_global_actual(config)
    return jsonify([
        serializar_producto(fila, imagenes_por_producto.get(fila['id'], []), descuento_global)
        for fila in filas
    ])


@app.route('/api/productos', methods=['POST'])
@admin_requerido
def agregar_producto():
    datos, error = obtener_datos_producto()
    if error:
        return jsonify({'mensaje': error[0]}), error[1]
    archivos = request.files.getlist('imagenes') or request.files.getlist('imagen')
    rutas_imagenes, error_imagen = guardar_imagenes(archivos, obligatorias=True)
    if error_imagen:
        return jsonify({'mensaje': error_imagen}), 400
    with conexion() as conn:
        if not categoria_existe(conn, datos['categoria_id']):
            return jsonify({'mensaje': 'La categoría elegida no existe.'}), 400
        cursor = conn.execute('''
            INSERT INTO productos
              (nombre, precio, imagen, especificacion, descuento_porcentaje, categoria_id)
            VALUES (:nombre, :precio, :imagen, :especificacion, :descuento_porcentaje, :categoria_id)
        ''', {**datos, 'imagen': rutas_imagenes[0]})
        producto_id = cursor.lastrowid
        conn.executemany(
            'INSERT INTO imagenes_producto (producto_id, ruta_imagen) VALUES (?, ?)',
            [(producto_id, ruta) for ruta in rutas_imagenes]
        )
    return jsonify({'mensaje': 'Producto agregado con éxito', 'id': producto_id}), 201


@app.route('/api/productos/<int:producto_id>', methods=['PUT'])
@admin_requerido
def editar_producto(producto_id):
    datos, error = obtener_datos_producto()
    if error:
        return jsonify({'mensaje': error[0]}), error[1]
    with conexion() as conn:
        actual = conn.execute('SELECT imagen FROM productos WHERE id = ?', (producto_id,)).fetchone()
        if not actual:
            return jsonify({'mensaje': 'Producto no encontrado.'}), 404
        if not categoria_existe(conn, datos['categoria_id']):
            return jsonify({'mensaje': 'La categoría elegida no existe.'}), 400
        imagen = actual['imagen']
        archivos = request.files.getlist('imagenes') or request.files.getlist('imagen')
        rutas_imagenes, error_imagen = guardar_imagenes(archivos)
        if error_imagen:
            return jsonify({'mensaje': error_imagen}), 400
        if rutas_imagenes:
            imagen = rutas_imagenes[0]
        conn.execute('''
            UPDATE productos SET nombre=:nombre, precio=:precio, imagen=:imagen,
                especificacion=:especificacion, descuento_porcentaje=:descuento_porcentaje,
                categoria_id=:categoria_id WHERE id=:id
        ''', {**datos, 'imagen': imagen, 'id': producto_id})
        if rutas_imagenes:
            conn.executemany(
                'INSERT INTO imagenes_producto (producto_id, ruta_imagen) VALUES (?, ?)',
                [(producto_id, ruta) for ruta in rutas_imagenes]
            )
    return jsonify({'mensaje': 'Producto actualizado'})


@app.route('/api/productos/<int:producto_id>', methods=['DELETE'])
@admin_requerido
def eliminar_producto(producto_id):
    with conexion() as conn:
        cursor = conn.execute('DELETE FROM productos WHERE id = ?', (producto_id,))
    if not cursor.rowcount:
        return jsonify({'mensaje': 'Producto no encontrado.'}), 404
    return jsonify({'mensaje': 'Producto eliminado'})


def fecha_vigente(fecha_texto):
    if not fecha_texto:
        return False
    try:
        return datetime.fromisoformat(fecha_texto) > datetime.now()
    except ValueError:
        return False


def descuento_global_actual(configuracion):
    """Retorna un descuento global solamente si sigue vigente."""
    if not configuracion:
        return 0
    porcentaje = configuracion['descuento_global_porcentaje'] or 0
    return porcentaje if porcentaje > 0 and fecha_vigente(configuracion['fecha_fin_descuento']) else 0


def serializar_promocion(fila):
    descuento_global = descuento_global_actual(fila)
    return {
        'texto_promocion': fila['texto_promocion'] or '',
        'fecha_expiracion': fila['fecha_expiracion'],
        'activa': bool(fila['activa']),
        'vigente': bool(fila['activa']) and fecha_vigente(fila['fecha_expiracion']),
        'descuento_global_porcentaje': fila['descuento_global_porcentaje'] or 0,
        'fecha_fin_descuento': fila['fecha_fin_descuento'],
        'descuento_global_activo': descuento_global > 0,
        'descuento_global_vigente': descuento_global,
    }


@app.route('/api/configuracion-promocion', methods=['GET'])
@admin_requerido
def obtener_configuracion_promocion():
    with conexion() as conn:
        fila = conn.execute('''
            SELECT texto_promocion, fecha_expiracion, activa,
                   descuento_global_porcentaje, fecha_fin_descuento
            FROM configuracion_promocion WHERE id=1
        ''').fetchone()
    return jsonify(serializar_promocion(fila))


@app.route('/api/configuracion-promocion', methods=['PUT'])
@admin_requerido
def actualizar_configuracion_promocion():
    cuerpo = request.get_json(silent=True) or request.form
    texto = (cuerpo.get('texto_promocion') or '').strip()
    fecha = (cuerpo.get('fecha_expiracion') or '').strip() or None
    activa = cuerpo.get('activa', False)
    descuento_texto = str(cuerpo.get('descuento_global_porcentaje', '0')).strip()
    fecha_fin_descuento = (cuerpo.get('fecha_fin_descuento') or '').strip() or None
    activa = activa is True or activa == 1 or str(activa).lower() in {'1', 'true', 'on'}
    if activa and (not texto or not fecha):
        return jsonify({'mensaje': 'Para activar una campaña indicá texto y fecha de expiración.'}), 400
    try:
        descuento_global = int(descuento_texto or 0)
    except ValueError:
        return jsonify({'mensaje': 'El descuento global no es válido.'}), 400
    if not 0 <= descuento_global <= 100:
        return jsonify({'mensaje': 'El descuento global debe estar entre 0 y 100.'}), 400
    if descuento_global > 0 and not fecha_fin_descuento:
        return jsonify({'mensaje': 'Indicá la fecha de finalización del descuento global.'}), 400
    if fecha:
        try:
            fecha = datetime.fromisoformat(fecha).isoformat(timespec='minutes')
        except ValueError:
            return jsonify({'mensaje': 'La fecha de expiración no es válida.'}), 400
    if fecha_fin_descuento:
        try:
            fecha_fin_descuento = datetime.fromisoformat(fecha_fin_descuento).isoformat(timespec='minutes')
        except ValueError:
            return jsonify({'mensaje': 'La fecha de finalización del descuento no es válida.'}), 400
    with conexion() as conn:
        conn.execute('''
            UPDATE configuracion_promocion
            SET texto_promocion=?, fecha_expiracion=?, activa=?,
                descuento_global_porcentaje=?, fecha_fin_descuento=?
            WHERE id=1
        ''', (texto, fecha, int(activa), descuento_global, fecha_fin_descuento))
        fila = conn.execute('''
            SELECT texto_promocion, fecha_expiracion, activa,
                   descuento_global_porcentaje, fecha_fin_descuento
            FROM configuracion_promocion WHERE id=1
        ''').fetchone()
    return jsonify({'mensaje': 'Campaña actualizada', **serializar_promocion(fila)})


@app.route('/api/promocion-activa', methods=['GET'])
def obtener_promocion_activa():
    """Endpoint público: sólo marca vigente una promoción activa y no expirada."""
    with conexion() as conn:
        fila = conn.execute('''
            SELECT texto_promocion, fecha_expiracion, activa,
                   descuento_global_porcentaje, fecha_fin_descuento
            FROM configuracion_promocion WHERE id=1
        ''').fetchone()
    promocion = serializar_promocion(fila)
    return jsonify({
        'activa': promocion['vigente'],
        'texto_promocion': promocion['texto_promocion'] if promocion['vigente'] else '',
        'fecha_expiracion': promocion['fecha_expiracion'] if promocion['vigente'] else None,
        'descuento_global_porcentaje': promocion['descuento_global_vigente'],
        'fecha_fin_descuento': promocion['fecha_fin_descuento'] if promocion['descuento_global_activo'] else None,
    })


@app.route('/api/categorias', methods=['GET'])
def obtener_categorias():
    with conexion() as conn:
        filas = conn.execute('''
            SELECT c.id, c.nombre, c.parent_id, p.nombre AS parent_nombre,
                   COUNT(pr.id) AS productos
            FROM categorias c
            LEFT JOIN categorias p ON p.id = c.parent_id
            LEFT JOIN productos pr ON pr.categoria_id = c.id
            GROUP BY c.id
            ORDER BY COALESCE(c.parent_id, c.id), c.parent_id IS NOT NULL, c.nombre COLLATE NOCASE
        ''').fetchall()
    return jsonify([dict(fila) for fila in filas])


@app.route('/api/categorias', methods=['POST'])
@admin_requerido
def agregar_categoria():
    cuerpo = request.get_json(silent=True) or request.form
    nombre = (cuerpo.get('nombre') or '').strip()
    parent_id = (cuerpo.get('parent_id') or '').strip()
    if not nombre:
        return jsonify({'mensaje': 'El nombre de la categoría es obligatorio.'}), 400
    try:
        parent_id = int(parent_id) if parent_id else None
    except ValueError:
        return jsonify({'mensaje': 'La categoría padre no es válida.'}), 400
    try:
        with conexion() as conn:
            if parent_id and not categoria_existe(conn, parent_id):
                return jsonify({'mensaje': 'La categoría padre no existe.'}), 400
            cursor = conn.execute('INSERT INTO categorias (nombre, parent_id) VALUES (?, ?)', (nombre, parent_id))
        return jsonify({'id': cursor.lastrowid, 'mensaje': 'Categoría creada'}), 201
    except sqlite3.IntegrityError:
        return jsonify({'mensaje': 'Ya existe una categoría con ese nombre.'}), 409


@app.route('/api/categorias/<int:categoria_id>', methods=['PUT'])
@admin_requerido
def editar_categoria(categoria_id):
    cuerpo = request.get_json(silent=True) or request.form
    nombre = (cuerpo.get('nombre') or '').strip()
    parent_id = (cuerpo.get('parent_id') or '').strip()
    if not nombre:
        return jsonify({'mensaje': 'El nombre de la categoría es obligatorio.'}), 400
    try:
        parent_id = int(parent_id) if parent_id else None
    except ValueError:
        return jsonify({'mensaje': 'La categoría padre no es válida.'}), 400
    if parent_id == categoria_id:
        return jsonify({'mensaje': 'Una categoría no puede ser su propia categoría padre.'}), 400
    try:
        with conexion() as conn:
            if parent_id and not categoria_existe(conn, parent_id):
                return jsonify({'mensaje': 'La categoría padre no existe.'}), 400
            cursor = conn.execute('UPDATE categorias SET nombre=?, parent_id=? WHERE id=?', (nombre, parent_id, categoria_id))
        if not cursor.rowcount:
            return jsonify({'mensaje': 'Categoría no encontrada.'}), 404
        return jsonify({'mensaje': 'Categoría actualizada'})
    except sqlite3.IntegrityError:
        return jsonify({'mensaje': 'Ya existe una categoría con ese nombre.'}), 409


@app.route('/api/categorias/<int:categoria_id>', methods=['DELETE'])
@admin_requerido
def eliminar_categoria(categoria_id):
    with conexion() as conn:
        productos = conn.execute('SELECT COUNT(*) FROM productos WHERE categoria_id=?', (categoria_id,)).fetchone()[0]
        hijas = conn.execute('SELECT COUNT(*) FROM categorias WHERE parent_id=?', (categoria_id,)).fetchone()[0]
        if productos or hijas:
            return jsonify({'mensaje': 'No se puede eliminar: tiene productos o subcategorías asignadas.'}), 409
        cursor = conn.execute('DELETE FROM categorias WHERE id=?', (categoria_id,))
    if not cursor.rowcount:
        return jsonify({'mensaje': 'Categoría no encontrada.'}), 404
    return jsonify({'mensaje': 'Categoría eliminada'})


if __name__ == '__main__':
    app.run(debug=True)
