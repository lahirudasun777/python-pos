"""
Simple POS - Flask + SQLite
Roles: admin (everything) and cashier (POS + own sales only)
Run:  pip install -r requirements.txt  ->  python app.py  ->  http://127.0.0.1:5000
Default login: admin / admin123   |   cashier / cashier123  (change after first login)
"""
import os
import sqlite3
from datetime import datetime, date
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, g, jsonify, abort)
from werkzeug.security import generate_password_hash, check_password_hash

from werkzeug.security import generate_password_hash as _gph
generate_password_hash = lambda pw: _gph(pw, method="pbkdf2:sha256")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pos.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("POS_SECRET_KEY", "change-this-secret-key")
app.config["SHOP_NAME"] = os.environ.get("POS_SHOP_NAME", "My Shop")
app.config["CURRENCY"] = os.environ.get("POS_CURRENCY", "Rs.")
app.config["TAX_RATE"] = float(os.environ.get("POS_TAX_RATE", "0"))  # e.g. 0.18 for 18%


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','cashier')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    barcode TEXT UNIQUE,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    price REAL NOT NULL,
    cost REAL NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    low_stock INTEGER NOT NULL DEFAULT 5,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    subtotal REAL NOT NULL,
    discount REAL NOT NULL DEFAULT 0,
    tax REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL,
    paid REAL NOT NULL,
    change_due REAL NOT NULL,
    payment_method TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    qty INTEGER NOT NULL,
    line_total REAL NOT NULL
);
"""


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        now = datetime.now().isoformat(timespec="seconds")
        db.execute("INSERT INTO users (username, full_name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                   ("admin", "Administrator", generate_password_hash("admin123"), "admin", now))
        db.execute("INSERT INTO users (username, full_name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                   ("cashier", "Cashier One", generate_password_hash("cashier123"), "cashier", now))
        # sample data so the POS isn't empty on first run
        for c in ("Beverages", "Snacks", "Grocery", "Household"):
            db.execute("INSERT INTO categories (name) VALUES (?)", (c,))
        samples = [
            ("Coca-Cola 400ml", "1001", 1, 150, 110, 48),
            ("Mineral Water 1L", "1002", 1, 100, 60, 60),
            ("Milk Tea Pack", "1003", 1, 220, 160, 25),
            ("Potato Chips", "2001", 2, 180, 120, 30),
            ("Chocolate Bar", "2002", 2, 250, 180, 4),
            ("Cream Crackers", "2003", 2, 320, 240, 20),
            ("Basmati Rice 1kg", "3001", 3, 690, 560, 40),
            ("White Sugar 1kg", "3002", 3, 290, 240, 35),
            ("Dhal 500g", "3003", 3, 210, 165, 22),
            ("Dish Wash Liquid", "4001", 4, 450, 330, 15),
            ("Toilet Tissue 4pk", "4002", 4, 560, 420, 3),
            ("Laundry Soap", "4003", 4, 120, 85, 50),
        ]
        db.executemany("INSERT INTO products (name, barcode, category_id, price, cost, stock) VALUES (?,?,?,?,?,?)",
                       samples)
    db.commit()
    db.close()


# ---------------------------------------------------------------- auth helpers
def current_user():
    if "user_id" not in session:
        return None
    if "user" not in g:
        g.user = get_db().execute("SELECT * FROM users WHERE id=? AND active=1",
                                  (session["user_id"],)).fetchone()
    return g.user


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if current_user() is None:
            session.clear()
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if current_user()["role"] != "admin":
            flash("Admin access only.", "error")
            return redirect(url_for("pos"))
        return view(*a, **kw)
    return wrapped


@app.context_processor
def inject_globals():
    return {"me": current_user(), "shop": app.config["SHOP_NAME"],
            "cur": app.config["CURRENCY"], "tax_rate": app.config["TAX_RATE"]}


@app.template_filter("money")
def money(v):
    return f"{app.config['CURRENCY']} {float(v or 0):,.2f}"


@app.template_filter("dt")
def fmt_dt(v):
    try:
        return datetime.fromisoformat(v).strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return v


# ---------------------------------------------------------------- auth routes
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("home"))
    if request.method == "POST":
        u = get_db().execute("SELECT * FROM users WHERE username=?",
                             (request.form.get("username", "").strip(),)).fetchone()
        if u and u["active"] and check_password_hash(u["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = u["id"]
            nxt = request.args.get("next")
            if nxt and nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("home"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    return redirect(url_for("dashboard" if current_user()["role"] == "admin" else "pos"))


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        me = current_user()
        if not check_password_hash(me["password_hash"], request.form.get("current", "")):
            flash("Current password is wrong.", "error")
        elif len(request.form.get("new", "")) < 6:
            flash("New password must be at least 6 characters.", "error")
        elif request.form["new"] != request.form.get("confirm"):
            flash("Passwords don't match.", "error")
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (generate_password_hash(request.form["new"]), me["id"]))
            db.commit()
            flash("Password updated.", "ok")
            return redirect(url_for("home"))
    return render_template("account.html")


# ---------------------------------------------------------------- dashboard (admin)
@app.route("/dashboard")
@admin_required
def dashboard():
    db = get_db()
    today = date.today().isoformat()
    month = today[:7]
    q = "SELECT COUNT(*) n, COALESCE(SUM(total),0) s FROM sales WHERE status='completed' AND created_at LIKE ?"
    t = db.execute(q, (today + "%",)).fetchone()
    m = db.execute(q, (month + "%",)).fetchone()
    profit_today = db.execute("""
        SELECT COALESCE(SUM(si.line_total - si.qty * COALESCE(p.cost,0)),0)
        FROM sale_items si JOIN sales s ON s.id = si.sale_id
        LEFT JOIN products p ON p.id = si.product_id
        WHERE s.status='completed' AND s.created_at LIKE ?""", (today + "%",)).fetchone()[0]
    low = db.execute("SELECT * FROM products WHERE active=1 AND stock <= low_stock ORDER BY stock").fetchall()
    top = db.execute("""
        SELECT si.name, SUM(si.qty) qty, SUM(si.line_total) amt FROM sale_items si
        JOIN sales s ON s.id=si.sale_id WHERE s.status='completed' AND s.created_at LIKE ?
        GROUP BY si.name ORDER BY qty DESC LIMIT 5""", (month + "%",)).fetchall()
    recent = db.execute("""SELECT s.*, u.full_name FROM sales s JOIN users u ON u.id=s.user_id
                           ORDER BY s.id DESC LIMIT 8""").fetchall()
    # last 7 days chart
    days = db.execute("""
        SELECT substr(created_at,1,10) d, SUM(total) s FROM sales
        WHERE status='completed' AND created_at >= date('now','localtime','-6 day')
        GROUP BY d""").fetchall()
    by_day = {r["d"]: r["s"] for r in days}
    from datetime import timedelta
    chart = []
    for i in range(6, -1, -1):
        d = date.today() - timedelta(days=i)
        chart.append({"label": d.strftime("%a"), "value": by_day.get(d.isoformat(), 0)})
    peak = max([c["value"] for c in chart] + [1])
    return render_template("dashboard.html", t=t, m=m, profit_today=profit_today, low=low,
                           top=top, recent=recent, chart=chart, peak=peak)


# ---------------------------------------------------------------- POS (both roles)
@app.route("/pos")
@login_required
def pos():
    db = get_db()
    cats = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    prods = db.execute("""SELECT p.*, c.name cat FROM products p LEFT JOIN categories c ON c.id=p.category_id
                          WHERE p.active=1 ORDER BY p.name""").fetchall()
    return render_template("pos.html", cats=cats, prods=[dict(p) for p in prods])


@app.route("/api/checkout", methods=["POST"])
@login_required
def checkout():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not items:
        return jsonify(ok=False, error="Cart is empty"), 400
    db = get_db()
    lines, subtotal = [], 0.0
    for it in items:
        try:
            pid, qty = int(it["id"]), int(it["qty"])
        except (KeyError, ValueError, TypeError):
            return jsonify(ok=False, error="Bad item"), 400
        if qty <= 0:
            continue
        p = db.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
        if not p:
            return jsonify(ok=False, error="Product not found"), 400
        if p["stock"] < qty:
            return jsonify(ok=False, error=f"Only {p['stock']} left of {p['name']}"), 400
        lt = round(p["price"] * qty, 2)
        subtotal += lt
        lines.append((p, qty, lt))
    if not lines:
        return jsonify(ok=False, error="Cart is empty"), 400

    subtotal = round(subtotal, 2)
    try:
        discount = max(0.0, min(float(data.get("discount") or 0), subtotal))
    except ValueError:
        discount = 0.0
    tax = round((subtotal - discount) * app.config["TAX_RATE"], 2)
    total = round(subtotal - discount + tax, 2)
    method = data.get("method") if data.get("method") in ("cash", "card", "qr") else "cash"
    try:
        paid = float(data.get("paid") or 0)
    except ValueError:
        paid = 0.0
    if method != "cash":
        paid = total
    if paid + 1e-9 < total:
        return jsonify(ok=False, error="Paid amount is less than total"), 400

    now = datetime.now()
    try:
        cur = db.execute("""INSERT INTO sales (invoice_no, user_id, subtotal, discount, tax, total, paid,
                            change_due, payment_method, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         ("TMP", current_user()["id"], subtotal, discount, tax, total, paid,
                          round(paid - total, 2), method, now.isoformat(timespec="seconds")))
        sid = cur.lastrowid
        inv = f"INV-{now:%y%m%d}-{sid:05d}"
        db.execute("UPDATE sales SET invoice_no=? WHERE id=?", (inv, sid))
        for p, qty, lt in lines:
            db.execute("INSERT INTO sale_items (sale_id, product_id, name, price, qty, line_total) VALUES (?,?,?,?,?,?)",
                       (sid, p["id"], p["name"], p["price"], qty, lt))
            db.execute("UPDATE products SET stock = stock - ? WHERE id=?", (qty, p["id"]))
        db.commit()
    except Exception:
        db.rollback()
        return jsonify(ok=False, error="Could not save sale"), 500
    return jsonify(ok=True, sale_id=sid, invoice=inv, change=round(paid - total, 2))


# ---------------------------------------------------------------- sales
@app.route("/sales")
@login_required
def sales():
    me = current_user()
    db = get_db()
    d_from = request.args.get("from") or date.today().replace(day=1).isoformat()
    d_to = request.args.get("to") or date.today().isoformat()
    sql = """SELECT s.*, u.full_name FROM sales s JOIN users u ON u.id=s.user_id
             WHERE substr(s.created_at,1,10) BETWEEN ? AND ?"""
    args = [d_from, d_to]
    if me["role"] != "admin":
        sql += " AND s.user_id=?"
        args.append(me["id"])
    elif request.args.get("user"):
        sql += " AND s.user_id=?"
        args.append(request.args["user"])
    rows = db.execute(sql + " ORDER BY s.id DESC", args).fetchall()
    done = [r for r in rows if r["status"] == "completed"]
    summary = {"count": len(done), "total": sum(r["total"] for r in done),
               "cash": sum(r["total"] for r in done if r["payment_method"] == "cash"),
               "card": sum(r["total"] for r in done if r["payment_method"] != "cash")}
    users = db.execute("SELECT id, full_name FROM users ORDER BY full_name").fetchall()
    return render_template("sales.html", rows=rows, summary=summary, d_from=d_from, d_to=d_to,
                           users=users, sel_user=request.args.get("user", ""))


def load_sale(sid):
    db = get_db()
    s = db.execute("SELECT s.*, u.full_name FROM sales s JOIN users u ON u.id=s.user_id WHERE s.id=?",
                   (sid,)).fetchone()
    if not s:
        abort(404)
    me = current_user()
    if me["role"] != "admin" and s["user_id"] != me["id"]:
        abort(403)
    items = db.execute("SELECT * FROM sale_items WHERE sale_id=?", (sid,)).fetchall()
    return s, items


@app.route("/sales/<int:sid>")
@login_required
def sale_detail(sid):
    s, items = load_sale(sid)
    return render_template("sale_detail.html", s=s, items=items)


@app.route("/receipt/<int:sid>")
@login_required
def receipt(sid):
    s, items = load_sale(sid)
    return render_template("receipt.html", s=s, items=items)


@app.route("/sales/<int:sid>/void", methods=["POST"])
@admin_required
def void_sale(sid):
    db = get_db()
    s = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
    if s and s["status"] == "completed":
        for it in db.execute("SELECT * FROM sale_items WHERE sale_id=?", (sid,)).fetchall():
            if it["product_id"]:
                db.execute("UPDATE products SET stock = stock + ? WHERE id=?", (it["qty"], it["product_id"]))
        db.execute("UPDATE sales SET status='void' WHERE id=?", (sid,))
        db.commit()
        flash(f"{s['invoice_no']} voided and stock returned.", "ok")
    return redirect(url_for("sale_detail", sid=sid))


# ---------------------------------------------------------------- products (admin)
@app.route("/products")
@admin_required
def products():
    db = get_db()
    q = request.args.get("q", "").strip()
    sql = """SELECT p.*, c.name cat FROM products p LEFT JOIN categories c ON c.id=p.category_id"""
    args = []
    if q:
        sql += " WHERE p.name LIKE ? OR p.barcode LIKE ?"
        args = [f"%{q}%", f"%{q}%"]
    rows = db.execute(sql + " ORDER BY p.active DESC, p.name", args).fetchall()
    return render_template("products.html", rows=rows, q=q)


@app.route("/products/new", methods=["GET", "POST"])
@app.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def product_form(pid=None):
    db = get_db()
    p = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone() if pid else None
    if pid and not p:
        abort(404)
    if request.method == "POST":
        f = request.form
        try:
            vals = (f["name"].strip(), f.get("barcode", "").strip() or None,
                    int(f["category_id"]) if f.get("category_id") else None,
                    float(f["price"]), float(f.get("cost") or 0), int(f.get("stock") or 0),
                    int(f.get("low_stock") or 5), 1 if f.get("active") else 0)
            if not vals[0] or vals[3] < 0:
                raise ValueError
        except (ValueError, KeyError):
            flash("Please check the fields — name and a valid price are required.", "error")
            return render_template("product_form.html", p=f, cats=cats_list())
        try:
            if p:
                db.execute("""UPDATE products SET name=?, barcode=?, category_id=?, price=?, cost=?, stock=?,
                              low_stock=?, active=? WHERE id=?""", vals + (pid,))
            else:
                db.execute("""INSERT INTO products (name, barcode, category_id, price, cost, stock, low_stock, active)
                              VALUES (?,?,?,?,?,?,?,?)""", vals)
            db.commit()
        except sqlite3.IntegrityError:
            flash("That barcode is already used by another product.", "error")
            return render_template("product_form.html", p=f, cats=cats_list())
        flash("Product saved.", "ok")
        return redirect(url_for("products"))
    return render_template("product_form.html", p=p, cats=cats_list())


@app.route("/products/<int:pid>/stock", methods=["POST"])
@admin_required
def add_stock(pid):
    try:
        qty = int(request.form.get("qty", 0))
    except ValueError:
        qty = 0
    if qty:
        db = get_db()
        db.execute("UPDATE products SET stock = MAX(0, stock + ?) WHERE id=?", (qty, pid))
        db.commit()
        flash("Stock updated.", "ok")
    return redirect(request.referrer or url_for("products"))


@app.route("/products/<int:pid>/delete", methods=["POST"])
@admin_required
def delete_product(pid):
    db = get_db()
    used = db.execute("SELECT 1 FROM sale_items WHERE product_id=? LIMIT 1", (pid,)).fetchone()
    if used:
        db.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
        flash("Product has sales history, so it was disabled instead of deleted.", "ok")
    else:
        db.execute("DELETE FROM products WHERE id=?", (pid,))
        flash("Product deleted.", "ok")
    db.commit()
    return redirect(url_for("products"))


# ---------------------------------------------------------------- categories (admin)
def cats_list():
    return get_db().execute("SELECT * FROM categories ORDER BY name").fetchall()


@app.route("/categories", methods=["GET", "POST"])
@admin_required
def categories():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            try:
                db.execute("INSERT INTO categories (name) VALUES (?)", (name,))
                db.commit()
                flash("Category added.", "ok")
            except sqlite3.IntegrityError:
                flash("Category already exists.", "error")
        return redirect(url_for("categories"))
    rows = db.execute("""SELECT c.*, COUNT(p.id) n FROM categories c LEFT JOIN products p ON p.category_id=c.id
                         GROUP BY c.id ORDER BY c.name""").fetchall()
    return render_template("categories.html", rows=rows)


@app.route("/categories/<int:cid>/rename", methods=["POST"])
@admin_required
def rename_category(cid):
    name = request.form.get("name", "").strip()
    if name:
        db = get_db()
        try:
            db.execute("UPDATE categories SET name=? WHERE id=?", (name, cid))
            db.commit()
        except sqlite3.IntegrityError:
            flash("Category already exists.", "error")
    return redirect(url_for("categories"))


@app.route("/categories/<int:cid>/delete", methods=["POST"])
@admin_required
def delete_category(cid):
    db = get_db()
    db.execute("DELETE FROM categories WHERE id=?", (cid,))
    db.commit()
    flash("Category deleted (its products are now uncategorised).", "ok")
    return redirect(url_for("categories"))


# ---------------------------------------------------------------- users (admin)
@app.route("/users")
@admin_required
def users():
    rows = get_db().execute("""SELECT u.*, (SELECT COUNT(*) FROM sales s WHERE s.user_id=u.id) n
                               FROM users u ORDER BY u.role, u.full_name""").fetchall()
    return render_template("users.html", rows=rows)


@app.route("/users/new", methods=["GET", "POST"])
@app.route("/users/<int:uid>/edit", methods=["GET", "POST"])
@admin_required
def user_form(uid=None):
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if uid and not u:
        abort(404)
    if request.method == "POST":
        f = request.form
        username, full_name = f.get("username", "").strip(), f.get("full_name", "").strip()
        role = f.get("role") if f.get("role") in ("admin", "cashier") else "cashier"
        active = 1 if f.get("active") else 0
        pw = f.get("password", "")
        if u and u["id"] == current_user()["id"]:
            role, active = "admin", 1  # never lock yourself out
        if not username or not full_name or (not u and len(pw) < 6) or (pw and len(pw) < 6):
            flash("Username and name are required; password must be 6+ characters.", "error")
            return render_template("user_form.html", u=f)
        try:
            if u:
                db.execute("UPDATE users SET username=?, full_name=?, role=?, active=? WHERE id=?",
                           (username, full_name, role, active, uid))
                if pw:
                    db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), uid))
            else:
                db.execute("""INSERT INTO users (username, full_name, password_hash, role, active, created_at)
                              VALUES (?,?,?,?,?,?)""", (username, full_name, generate_password_hash(pw), role,
                                                       active, datetime.now().isoformat(timespec="seconds")))
            db.commit()
        except sqlite3.IntegrityError:
            flash("Username already taken.", "error")
            return render_template("user_form.html", u=f)
        flash("User saved.", "ok")
        return redirect(url_for("users"))
    return render_template("user_form.html", u=u)


@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, msg="You don't have access to this page."), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, msg="Page not found."), 404


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
