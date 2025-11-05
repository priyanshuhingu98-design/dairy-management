from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from datetime import datetime, date
from decimal import Decimal
import os
from dotenv import load_dotenv
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import pandas as pd
from werkzeug.utils import secure_filename
from math import ceil

# ✅ Load .env if present
load_dotenv('.env') if os.path.exists('.env') else None

# ✅ Flask app setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_secret')
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'static/logos')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.db'  # ✅ SQLite only
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ✅ Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ✅ SQLAlchemy and Login setup
db = SQLAlchemy()
db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)


# -------------------- MODELS --------------------
class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    # optional role field - not mandatory for this change
    # role = db.Column(db.String(20), default='user')

class Dairy(db.Model):
    __tablename__ = 'dairies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    logo_path = db.Column(db.String(255))

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    dairy_id = db.Column(db.Integer, db.ForeignKey('dairies.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    unit = db.Column(db.String(50), default='litre')
    cost_price = db.Column(db.Numeric(10,2), nullable=False)
    sell_price = db.Column(db.Numeric(10,2), nullable=False)
    min_stock = db.Column(db.Numeric(10,2), default=0)
    current_stock = db.Column(db.Numeric(12,2), default=0)
    dairy = db.relationship('Dairy')

class StockIn(db.Model):
    __tablename__ = 'stock_in'
    id = db.Column(db.Integer, primary_key=True)
    dairy_id = db.Column(db.Integer, db.ForeignKey('dairies.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    qty = db.Column(db.Numeric(10,2), nullable=False)
    cost_price = db.Column(db.Numeric(10,2), nullable=False)
    date = db.Column(db.Date, nullable=False)
    remarks = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship('Product')
    dairy = db.relationship('Dairy')

class Sale(db.Model):
    __tablename__ = 'sales'
    id = db.Column(db.Integer, primary_key=True)
    dairy_id = db.Column(db.Integer, db.ForeignKey('dairies.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    qty = db.Column(db.Numeric(10,2), nullable=False)
    selling_price = db.Column(db.Numeric(10,2), nullable=False)
    date = db.Column(db.Date, nullable=False)
    remarks = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship('Product')
    dairy = db.relationship('Dairy')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# -------------------- Helpers --------------------
def current_dairy():
    did = session.get('dairy_id')
    if did:
        d = Dairy.query.get(did)
        if d:
            return {'id': d.id, 'name': d.name, 'logo': d.logo_path}
    return None

# -------------------- Routes (unchanged core logic) --------------------
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    if session.get('dairy_id'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            login_user(user)
            session.pop('dairy_id', None)
            return redirect(url_for('admin_dashboard'))
        dairy = Dairy.query.filter_by(username=username, password=password).first()
        if dairy:
            session['dairy_id'] = dairy.id
            session['dairy_name'] = dairy.name
            session['dairy_logo'] = dairy.logo_path
            return redirect(url_for('dashboard'))
        flash('Invalid credentials','danger')
    return render_template('login.html', dairy=current_dairy())

@app.route('/logout')
def logout():
    if current_user.is_authenticated:
        logout_user()
    session.pop('dairy_id', None)
    session.pop('dairy_name', None)
    session.pop('dairy_logo', None)
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    dairies = Dairy.query.all()
    return render_template('admin_dashboard.html', dairies=dairies)

@app.route('/admin/dairies/add', methods=['GET','POST'])
@login_required
def add_dairy():
    if request.method=='POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        logo = request.files.get('logo')
        logo_path = None
        if logo and logo.filename:
            filename = secure_filename(logo.filename)
            dest = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            logo.save(dest)
            logo_path = dest
        d = Dairy(name=name, username=username, password=password, logo_path=logo_path)
        db.session.add(d); db.session.commit()
        flash('Dairy added','success')
        return redirect(url_for('admin_dashboard'))
    return render_template('add_dairy.html')

@app.route('/admin/dairies/<int:did>/view')
@login_required
def admin_view_dairy(did):
    d = Dairy.query.get_or_404(did)
    session['dairy_id'] = d.id
    session['dairy_name'] = d.name
    session['dairy_logo'] = d.logo_path
    flash(f'Now viewing as {d.name}','info')
    return redirect(url_for('dashboard'))

# Dashboard route (kept your existing logic)
@app.route('/dashboard')
def dashboard():
    d = current_dairy()
    if not d:
        flash('Please login as dairy or admin (impersonate)', 'warning')
        return redirect(url_for('login'))

    dairy_id = d['id']
    products = Product.query.filter_by(dairy_id=dairy_id).all()

    f1 = request.args.get('from')
    f2 = request.args.get('to')

    try:
        f1d = datetime.strptime(f1, '%Y-%m-%d').date() if f1 else datetime.today().date()
        f2d = datetime.strptime(f2, '%Y-%m-%d').date() if f2 else datetime.today().date()
    except:
        f1d = f2d = datetime.today().date()

    stock_ins = StockIn.query.filter(
        StockIn.dairy_id == dairy_id,
        StockIn.date.between(f1d, f2d)
    ).all()

    sales = Sale.query.filter(
        Sale.dairy_id == dairy_id,
        Sale.date.between(f1d, f2d)
    ).all()

    total_stock_value = sum([p.current_stock * p.cost_price for p in products])
    total_revenue = sum([s.qty * s.selling_price for s in sales])
    total_cogs = sum([s.qty * s.product.cost_price for s in sales])
    profit = total_revenue - total_cogs

    product_stock_summary = []
    for p in products:
        stock_in_qty = sum(si.qty for si in stock_ins if si.product_id == p.id)
        sale_qty = sum(s.qty for s in sales if s.product_id == p.id)
        closing_stock = p.current_stock
        product_stock_summary.append({
            'name': p.name,
            'stock_in': stock_in_qty,
            'stock_out': sale_qty,
            'closing_stock': closing_stock
        })

    return render_template(
        'dashboard.html',
        products=products,
        total_stock_value=total_stock_value,
        total_revenue=total_revenue,
        total_cogs=total_cogs,
        profit=profit,
        product_stock_summary=product_stock_summary,
        f1=f1d.strftime('%Y-%m-%d'),
        f2=f2d.strftime('%Y-%m-%d'),
        dairy=d
    )

# Products CRUD (unchanged)
@app.route('/products')
def products():
    d = current_dairy()
    if not d: return redirect(url_for('login'))
    products = Product.query.filter_by(dairy_id=d['id']).all()
    return render_template('products.html', products=products, dairy=d)

@app.route('/products/add', methods=['GET','POST'])
def add_product():
    d = current_dairy()
    if not d: return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name']
        unit = request.form['unit']
        cost_price = request.form['cost_price'] or 0
        sell_price = request.form['sell_price'] or 0
        min_stock = request.form.get('min_stock') or 0
        p = Product(
            dairy_id=d['id'],
            name=name,
            unit=unit,
            cost_price=cost_price,
            sell_price=sell_price,
            min_stock=min_stock
        )
        db.session.add(p)
        db.session.commit()
        flash('Product added', 'success')
        return redirect(url_for('products'))
    return render_template('product_form.html', action='Add', dairy=d, product=None)

@app.route('/products/edit/<int:pid>', methods=['GET','POST'])
def edit_product(pid):
    d = current_dairy()
    if not d: return redirect(url_for('login'))
    p = Product.query.get_or_404(pid)
    if p.dairy_id != d['id']: abort(403)
    if request.method == 'POST':
        p.name = request.form['name']
        p.unit = request.form['unit']
        p.cost_price = request.form['cost_price'] or 0
        p.sell_price = request.form['sell_price'] or 0
        p.min_stock = request.form.get('min_stock') or 0
        db.session.commit()
        flash('Product updated', 'success')
        return redirect(url_for('products'))
    return render_template('product_form.html', product=p, action='Edit', dairy=d)

@app.route('/products/delete/<int:pid>', methods=['POST'])
def delete_product(pid):
    d = current_dairy()
    if not d: return redirect(url_for('login'))
    p = Product.query.get_or_404(pid)
    if p.dairy_id != d['id']: abort(403)
    db.session.delete(p)
    db.session.commit()
    flash('Product deleted', 'success')
    return redirect(url_for('products'))

# Stock In routes (unchanged)
@app.route('/stock_in', methods=['GET','POST'])
def stock_in_page():
    d = current_dairy(); 
    if not d: return redirect(url_for('login'))
    products = Product.query.filter_by(dairy_id=d['id']).all()
    if request.method=='POST':
        pid = int(request.form['product_id']); qty = Decimal(request.form['qty'] or 0)
        cost_price = Decimal(request.form['cost_price'] or 0); date_str = request.form.get('date') or date.today().isoformat()
        remarks = request.form.get('remarks') or ''
        st = StockIn(dairy_id=d['id'], product_id=pid, qty=qty, cost_price=cost_price, date=datetime.strptime(date_str, '%Y-%m-%d').date(), remarks=remarks)
        db.session.add(st)
        prod = Product.query.get(pid)
        prod.current_stock = Decimal(prod.current_stock or 0) + qty
        prod.cost_price = cost_price
        db.session.commit(); flash('Stock added','success'); return redirect(url_for('stock_in_page'))
    trans = StockIn.query.filter_by(dairy_id=d['id']).order_by(StockIn.date.desc()).limit(200).all()
    today = datetime.today().strftime('%Y-%m-%d') 
    return render_template('stock_in.html', products=products, trans=trans, dairy=d, today=today)

@app.route('/stock_in/edit/<int:sid>', methods=['GET','POST'])
def edit_stock_in(sid):
    d = current_dairy(); 
    if not d: return redirect(url_for('login'))
    st = StockIn.query.get_or_404(sid)
    if st.dairy_id != d['id']: abort(403)
    if request.method=='POST':
        old_qty = st.qty
        st.qty = Decimal(request.form['qty'] or 0)
        st.cost_price = Decimal(request.form['cost_price'] or 0)
        st.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        st.remarks = request.form.get('remarks') or ''
        prod = Product.query.get(st.product_id)
        prod.current_stock = Decimal(prod.current_stock or 0) - old_qty + st.qty
        db.session.commit(); flash('Stock entry updated','success'); 
        return redirect(url_for('stock_in_page'))
    today = datetime.today().strftime('%Y-%m-%d')    
    return render_template('stock_in_form.html', entry=st, dairy=d, today=today)

# Sales routes (unchanged)
@app.route('/sales', methods=['GET','POST'])
def sales_page():
    d = current_dairy(); 
    if not d: return redirect(url_for('login'))
    products = Product.query.filter_by(dairy_id=d['id']).all()
    if request.method=='POST':
        pid = int(request.form['product_id']); qty = Decimal(request.form['qty'] or 0)
        selling_price = Decimal(request.form['selling_price'] or 0); date_str = request.form.get('date') or date.today().isoformat()
        remarks = request.form.get('remarks') or ''
        sale = Sale(dairy_id=d['id'], product_id=pid, qty=qty, selling_price=selling_price, date=datetime.strptime(date_str, '%Y-%m-%d').date(), remarks=remarks)
        db.session.add(sale)
        prod = Product.query.get(pid)
        prod.current_stock = Decimal(prod.current_stock or 0) - qty
        prod.sell_price = selling_price
        db.session.commit(); flash('Sale recorded','success'); return redirect(url_for('sales_page'))
    sales = Sale.query.filter_by(dairy_id=d['id']).order_by(Sale.date.desc()).limit(200).all()
    today = datetime.today().strftime('%Y-%m-%d') 
    return render_template('sales.html', products=products, sales=sales, dairy=d ,today=today) 

@app.route('/sales/edit/<int:sid>', methods=['GET','POST'])
def edit_sale(sid):
    d = current_dairy(); 
    if not d: return redirect(url_for('login'))
    sale = Sale.query.get_or_404(sid)
    if sale.dairy_id != d['id']: abort(403)
    if request.method=='POST':
        old_qty = sale.qty
        sale.qty = Decimal(request.form['qty'] or 0)
        sale.selling_price = Decimal(request.form['selling_price'] or 0)
        sale.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        sale.remarks = request.form.get('remarks') or ''
        prod = Product.query.get(sale.product_id)
        prod.current_stock = Decimal(prod.current_stock or 0) + old_qty - sale.qty
        db.session.commit(); flash('Sale updated','success'); return redirect(url_for('sales_page'))
    today = datetime.today().strftime('%Y-%m-%d')    
    return render_template('sale_form.html', sale=sale, dairy=d,today=today)

@app.route('/sales/delete/<int:sid>', methods=['POST'])
def delete_sale(sid):
    d = current_dairy()
    if not d: return redirect(url_for('login'))
    sale = Sale.query.get_or_404(sid)
    if sale.dairy_id != d['id']: abort(403)
    prod = Product.query.get(sale.product_id)
    if prod:
        prod.current_stock = Decimal(prod.current_stock or 0) + sale.qty
    db.session.delete(sale)
    db.session.commit()
    flash('Sale entry deleted', 'success')
    return redirect(url_for('sales_page'))

# Reports listing route (kept your logic, minor cleanup)
@app.route('/reports', methods=['GET', 'POST'])
def reports():
    dairies = Dairy.query.all() if current_user.is_authenticated else None
    d = current_dairy()
    rows = []
    totals = {'in_qty': 0, 'out_qty': 0, 'cost_val': 0, 'sell_val': 0, 'profit': 0}
    today_str = datetime.today().strftime('%Y-%m-%d')
    f1 = request.form.get('from') or request.args.get('from') or today_str
    f2 = request.form.get('to') or request.args.get('to') or today_str
    pid = request.form.get('product') or request.args.get('product')
    did = request.form.get('dairy') or request.args.get('dairy') or (d['id'] if d else None)

    try:
        f1d = datetime.strptime(f1, '%Y-%m-%d').date() if f1 else None
        f2d = datetime.strptime(f2, '%Y-%m-%d').date() if f2 else None
    except:
        f1d = f2d = None

    si_query = StockIn.query
    s_query = Sale.query

    if did and str(did).isdigit():
        did_int = int(did)
        si_query = si_query.filter(StockIn.dairy_id == did_int)
        s_query = s_query.filter(Sale.dairy_id == did_int)
    if f1d:
        si_query = si_query.filter(StockIn.date >= f1d)
        s_query = s_query.filter(Sale.date >= f1d)
    if f2d:
        si_query = si_query.filter(StockIn.date <= f2d)
        s_query = s_query.filter(Sale.date <= f2d)
    if pid and str(pid).isdigit():
        pid_int = int(pid)
        si_query = si_query.filter(StockIn.product_id == pid_int)
        s_query = s_query.filter(Sale.product_id == pid_int)

    sis = si_query.all()
    ss = s_query.all()

    for entry in sis:
        rows.append({
            'dairy': entry.dairy.name,
            'logo': entry.dairy.logo_path,
            'date': entry.date,
            'product': entry.product.name,
            'in_qty': float(entry.qty),
            'out_qty': 0.0,
            'cost_price': float(entry.cost_price),
            'sell_price': '',
            'profit': 0.0,
            'remarks': entry.remarks or ''
        })
        totals['in_qty'] += float(entry.qty)
        totals['cost_val'] += float(entry.qty) * float(entry.cost_price)

    for s in ss:
        profit = float(s.qty * (s.selling_price - s.product.cost_price))
        rows.append({
            'dairy': s.dairy.name,
            'logo': s.dairy.logo_path,
            'date': s.date,
            'product': s.product.name,
            'in_qty': 0.0,
            'out_qty': float(s.qty),
            'cost_price': float(s.product.cost_price),
            'sell_price': float(s.selling_price),
            'profit': profit,
            'remarks': s.remarks or ''
        })
        totals['out_qty'] += float(s.qty)
        totals['sell_val'] += float(s.qty) * float(s.selling_price)
        totals['profit'] += profit

    rows = sorted(rows, key=lambda x: x['date'], reverse=True)

    # Pagination
    page = int(request.args.get('page', 1))
    per_page = 10
    start = (page - 1) * per_page
    end = start + per_page
    total_pages = ceil(len(rows) / per_page) if rows else 1
    paginated_rows = rows[start:end]

    # Save Excel
    if rows:
        df = pd.DataFrame(rows)
        output_dir = os.path.join('static', 'reports')
        os.makedirs(output_dir, exist_ok=True)
        excel_path = os.path.join(output_dir, 'report_v3.xlsx')
        df.to_excel(excel_path, index=False)
        out = True
    else:
        out = False

    products = Product.query.filter_by(dairy_id=int(did)).all() if did and str(did).isdigit() else []

    return render_template('reports.html',
                           dairies=dairies,
                           products=products,
                           rows=paginated_rows,
                           totals=totals,
                           out=out,
                           f1=f1,
                           f2=f2,
                           pid=pid,
                           did=did,
                           dairy=d,
                           page=page,
                           total_pages=total_pages)

# -------------------- New/Updated PDF generator route (Modern Royal Blue, logo top-right, footer) --------------------
@app.route('/reports/pdf', endpoint='reports_pdf')
def reports_pdf():
    # Read filters
    f1 = request.args.get('from')
    f2 = request.args.get('to')
    pid = request.args.get('product')
    did = request.args.get('dairy')

    si_query = StockIn.query
    s_query = Sale.query

    try:
        if did and str(did).isdigit():
            did_int = int(did)
            si_query = si_query.filter(StockIn.dairy_id == did_int)
            s_query = s_query.filter(Sale.dairy_id == did_int)
        if f1:
            f1d = datetime.strptime(f1, '%Y-%m-%d').date()
            si_query = si_query.filter(StockIn.date >= f1d)
            s_query = s_query.filter(Sale.date >= f1d)
        if f2:
            f2d = datetime.strptime(f2, '%Y-%m-%d').date()
            si_query = si_query.filter(StockIn.date <= f2d)
            s_query = s_query.filter(Sale.date <= f2d)
    except Exception as e:
        # if parsing fails, ignore date filters
        f1d = f2d = None

    if pid and str(pid).isdigit():
        pid_int = int(pid)
        si_query = si_query.filter(StockIn.product_id == pid_int)
        s_query = s_query.filter(Sale.product_id == pid_int)

    sis = si_query.order_by(StockIn.date.desc()).all()
    ss = s_query.order_by(Sale.date.desc()).all()

    # Build rows and totals
    rows = []
    totals = {'in_qty': 0.0, 'out_qty': 0.0, 'cost_val': 0.0, 'sell_val': 0.0, 'profit': 0.0}

    for entry in sis:
        rows.append({
            'date': entry.date,
            'dairy': entry.dairy.name,
            'product': entry.product.name,
            'in_qty': float(entry.qty),
            'out_qty': 0.0,
            'cost_price': float(entry.cost_price),
            'sell_price': '',
            'profit': 0.0,
            'remarks': entry.remarks or ''
        })
        totals['in_qty'] += float(entry.qty)
        totals['cost_val'] += float(entry.qty) * float(entry.cost_price)

    for s in ss:
        profit = float(s.qty * (s.selling_price - s.product.cost_price))
        rows.append({
            'date': s.date,
            'dairy': s.dairy.name,
            'product': s.product.name,
            'in_qty': 0.0,
            'out_qty': float(s.qty),
            'cost_price': float(s.product.cost_price),
            'sell_price': float(s.selling_price),
            'profit': profit,
            'remarks': s.remarks or ''
        })
        totals['out_qty'] += float(s.qty)
        totals['sell_val'] += float(s.qty) * float(s.selling_price)
        totals['profit'] += profit

    rows = sorted(rows, key=lambda x: x['date'] or datetime.min.date(), reverse=True)

    # Prepare PDF
    buffer = BytesIO()
    page_size = landscape(A4)
    doc = SimpleDocTemplate(buffer, pagesize=page_size,
                            rightMargin=20, leftMargin=20, topMargin=60, bottomMargin=40)

    # Styles
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='TitleCenter', parent=styles['Title'], alignment=TA_CENTER, fontSize=20, leading=24))
    styles.add(ParagraphStyle(name='SubCenter', parent=styles['Normal'], alignment=TA_CENTER, fontSize=10))
    styles.add(ParagraphStyle(name='CardVal', parent=styles['Heading2'], alignment=TA_CENTER, fontSize=13, textColor=colors.HexColor('#D4AF37')))
    styles.add(ParagraphStyle(name='CardLabel', parent=styles['Normal'], alignment=TA_CENTER, fontSize=9, textColor=colors.white))
    styles.add(ParagraphStyle(name='Small', parent=styles['Normal'], fontSize=8))
    elems = []

    # Logo resolution: prefer dairy-specific logo if available, else placeholder
    dairy_obj = Dairy.query.get(int(did)) if did and str(did).isdigit() else None
    default_logo = os.path.join(app.root_path, 'static', 'logos', 'placeholder.png')
    logo_path = default_logo

    if dairy_obj and dairy_obj.logo_path:
        lp = dairy_obj.logo_path
        # if absolute path exists, use it
        if os.path.isabs(lp) and os.path.exists(lp):
            logo_path = lp
        else:
            # try relative to app.root_path
            possible = os.path.join(app.root_path, lp.lstrip('/'))
            if os.path.exists(possible):
                logo_path = possible

    # Header: we'll place logo at top-right by using a small table with two cells: left blank/title, right logo
    header_data = []

    # Prepare title column (left) and logo column (right)
    title_para = Paragraph(dairy_obj.name if dairy_obj else (current_dairy()['name'] if current_dairy() else "Dairy Report"), styles['TitleCenter'])
    # create a small RLImage if exists
    logo_img = None
    if os.path.exists(logo_path):
        try:
            logo_img = RLImage(logo_path)
            logo_img.drawHeight = 45
            logo_img.drawWidth = 120
        except Exception:
            logo_img = None

    # Build a header table: left column = title paragraphs stacked, right column = logo (if present)
    left_col = [title_para, Spacer(1,6), Paragraph("Stock & Sales Report", styles['SubCenter']),
                Spacer(1,6), Paragraph(f"Period: {f1 or '-'} to {f2 or '-'}", styles['SubCenter'])]
    # left content as a single paragraph (will be centered later)
    left_combined = []
    for item in left_col:
        left_combined.append(item)

    # A two-column table where left is the title block and right is logo
    if logo_img:
        header_table = Table([[left_combined, logo_img]], colWidths=[doc.width - 140, 120])
    else:
        header_table = Table([[left_combined, '']], colWidths=[doc.width - 140, 120])

    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))

    elems.append(header_table)
    elems.append(Spacer(1, 12))

    # Summary cards (3 cards) rendered as a 1-row table
    card_bg = colors.HexColor('#0B3D91')  # Royal Blue
    card_table = Table([
        [
            Paragraph(f"<b> <font color='#D4AF37'>Total Stock In</font></b><br/><font size=12 color='#D4AF37'>{totals['in_qty']:.2f}</font>", styles['Normal']),
            Paragraph(f"<b> <font color='#D4AF37'>Total Stock Out</font></b><br/><font size=12 color='#D4AF37'>{totals['out_qty']:.2f}</font>", styles['Normal']),
            Paragraph(f"<b> <font color='#D4AF37'>Total Profit</font></b><br/><font size=12 color='#D4AF37'>{totals['profit']:.2f}</font>", styles['Normal'])
        ]
    ], colWidths=[doc.width/3.0]*3)
    card_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), card_bg),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.white),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    elems.append(card_table)
    elems.append(Spacer(1, 14))

    # Build detailed table data
    table_data = []
    header = ['Date', 'Dairy', 'Product', 'Stock In', 'Stock Out', 'Cost P', 'S.P', 'P/L', 'Remarks']
    table_data.append(header)
    for r in rows:
        table_data.append([
            r['date'].isoformat() if hasattr(r['date'], 'isoformat') else str(r['date']),
            r['dairy'],
            r['product'],
            f"{r['in_qty']:.2f}" if r['in_qty'] else '',
            f"{r['out_qty']:.2f}" if r['out_qty'] else '',
            f"{r['cost_price']:.2f}" if r['cost_price'] != '' and r['cost_price'] is not None else '',
            f"{r['sell_price']:.2f}" if r['sell_price'] != '' and r['sell_price'] is not None else '',
            f"{r['profit']:.2f}" if r['profit'] else '',
            r['remarks'] or ''
        ])

    # Totals row
    table_data.append([
        'Totals', '', '',
        f"{totals['in_qty']:.2f}",
        f"{totals['out_qty']:.2f}",
        f"{totals['cost_val']:.2f}",
        f"{totals['sell_val']:.2f}",
        f"{totals['profit']:.2f}",
        ''
    ])

    # Column widths (tweak as necessary)
    col_widths = [70, 90, 140, 60, 60, 60, 60, 80, doc.width - (70+90+140+60+60+60+60+80)]
    report_table = Table(table_data, colWidths=col_widths, repeatRows=1)

    # Table styling: modern header (royal blue + gold), zebra rows
    report_table_style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0B3D91')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#D4AF37')),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('ALIGN', (3,1), (7,-2), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('BOX', (0,0), (-1,-1), 0.5, colors.black),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('FONTNAME', (0, len(table_data)-1), (-1, len(table_data)-1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, len(table_data)-1), (-1, len(table_data)-1), colors.HexColor('#F2F4F8')),
    ])

    # zebra body rows
    for i in range(1, len(table_data)-1):
        if i % 2 == 1:
            report_table_style.add('BACKGROUND', (0,i), (-1,i), colors.whitesmoke)

    report_table.setStyle(report_table_style)
    elems.append(report_table)

    # Footer function: page number + generated timestamp
    def _footer(canvas, doc):
        canvas.saveState()
        footer_text = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        page_num_text = f"Page {canvas.getPageNumber()}"
        width, height = page_size
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(20, 18, footer_text)
        canvas.drawRightString(width - 20, 18, page_num_text)
        canvas.restoreState()

    # Build PDF and return
    doc.build(elems, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='report_v3.pdf', mimetype='application/pdf')

# Utility: initdb
@app.cli.command('initdb')
def initdb():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        u = User(username='admin', password='admin'); db.session.add(u)
    if not Dairy.query.first():
        d = Dairy(name='Sample Dairy', username='dairy', password='dairy', logo_path=None); db.session.add(d); db.session.commit()
    db.session.commit()
    print('Initialized DB and created default admin (admin/admin) and sample dairy (dairy/dairy)')

if __name__=='__main__':
    app.run()
