from decimal import Decimal, InvalidOperation
from functools import wraps
import secrets
import re
import warnings
from pathlib import Path
from uuid import uuid4
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app, send_from_directory
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func
from PIL import Image, UnidentifiedImageError
from .extensions import db, limiter
from .models import User, Service, Order, OrderItem, StatusHistory, Payment, OrderPhoto

main = Blueprint("main", __name__)
auth = Blueprint("auth", __name__, url_prefix="/auth")
customer = Blueprint("customer", __name__, url_prefix="/customer")
admin = Blueprint("admin", __name__, url_prefix="/admin")
staff = Blueprint("staff", __name__, url_prefix="/staff")
delivery = Blueprint("delivery", __name__, url_prefix="/delivery")

STATUSES = ["Pending", "Confirmed", "Picked Up", "Received", "Processing",
            "Ironing", "Ready", "Out for Delivery", "Delivered", "Cancelled"]
DONE_STATUSES = ["Delivered", "Cancelled"]
STAFF_DONE_STATUSES = ["Ready", "Delivered", "Cancelled"]
GARMENTS = ["Shirt", "T-shirt", "Trousers", "Jeans", "Dress", "Skirt", "Saree", "Salwar suit", "Jacket", "Coat", "Blanket", "Curtains", "Bedsheet", "Other"]
STATUS_TRANSITIONS = {
    "Pending": ["Confirmed", "Cancelled"],
    "Confirmed": ["Picked Up", "Received", "Cancelled"],
    "Picked Up": ["Received", "Cancelled"],
    "Received": ["Processing", "Cancelled"],
    "Processing": ["Ironing", "Ready", "Cancelled"],
    "Ironing": ["Ready", "Cancelled"],
    "Ready": ["Out for Delivery", "Cancelled"],
    "Out for Delivery": ["Delivered", "Cancelled"],
    "Delivered": [],
    "Cancelled": [],
}
IMAGE_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}

def valid_phone(phone):
    return bool(re.fullmatch(r"\+?[0-9]{7,15}", phone))

def photo_folder():
    folder = Path(current_app.config["ORDER_UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    return folder

def validate_photo(uploaded):
    extension = uploaded.filename.rsplit(".", 1)[-1].lower() if "." in uploaded.filename else ""
    expected_format = IMAGE_FORMATS.get(extension)
    if not expected_format:
        return False
    try:
        uploaded.stream.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(uploaded.stream) as image:
                if image.format != expected_format:
                    return False
                image.verify()
            uploaded.stream.seek(0)
            with Image.open(uploaded.stream) as image:
                image.load()
        uploaded.stream.seek(0)
        return True
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        uploaded.stream.seek(0)
        return False

def save_private_photo(uploaded):
    uploaded.stream.seek(0)
    with Image.open(uploaded.stream) as image:
        image.load()
        fmt = image.format
        extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[fmt]
        if fmt == "JPEG" and image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        filename = f"{uuid4().hex}.{extension}"
        image.save(photo_folder() / filename, format=fmt, optimize=True)
    uploaded.stream.seek(0)
    return filename

def next_statuses(order, role):
    transitions = STATUS_TRANSITIONS.get(order.status, [])
    if role == "delivery_agent":
        transitions = [status for status in transitions if status in {"Picked Up", "Out for Delivery", "Delivered"}]
    elif role == "staff":
        transitions = [status for status in transitions if status != "Out for Delivery"]
    return transitions

def _free_team_member(role, exclude_id=None):
    column = Order.assigned_staff_id if role == "staff" else Order.delivery_agent_id
    finished = STAFF_DONE_STATUSES if role == "staff" else DONE_STATUSES
    for person in User.query.filter_by(role=role).order_by(User.id).all():
        if person.id != exclude_id and Order.query.filter(column == person.id, Order.status.notin_(finished)).count() == 0:
            return person
    return None

def _fill_unassigned():
    for role, field, label in (("staff", "assigned_staff_id", "laundry staff"), ("delivery_agent", "delivery_agent_id", "delivery agent")):
        column = getattr(Order, field)
        finished = STAFF_DONE_STATUSES if role == "staff" else DONE_STATUSES
        waiting = Order.query.filter(column.is_(None), Order.status.notin_(finished)).order_by(Order.created_at, Order.id).all()
        for order in waiting:
            person = _free_team_member(role)
            if not person:
                break
            setattr(order, field, person.id)
            db.session.add(StatusHistory(order_id=order.id, updated_by_id=order.created_by_id,
                status=order.status, note=f"Automatically assigned to {label} {person.name}"))

def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator

@main.route("/")
def home():
    services = Service.query.filter_by(active=True).order_by(Service.id).all()
    return render_template("home.html", services=services)

@main.route("/contact")
def contact():
    return render_template("contact.html")

@auth.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower() or None
        password = request.form.get("password", "")
        if not name or not valid_phone(phone) or len(password) < 8:
            flash("Enter your name and a phone number with 7–15 digits (optional leading +). Password must be at least 8 characters.", "danger")
            return render_template("auth/register.html")
        if User.query.filter_by(phone=phone).first() or (email and User.query.filter_by(email=email).first()):
            flash("That phone number or email is already registered.", "danger")
            return render_template("auth/register.html")
        user = User(name=name, phone=phone, email=email, role="customer")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Account created. Please sign in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html")

@auth.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if request.method == "POST":
        identity = request.form.get("identity", "").strip()
        user = User.query.filter((User.phone == identity) | (User.email == identity.lower())).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user)
            if user.role == "admin":
                return redirect(url_for("admin.dashboard"))
            if user.role == "staff":
                return redirect(url_for("staff.dashboard"))
            if user.role == "delivery_agent":
                return redirect(url_for("delivery.dashboard"))
            return redirect(url_for("customer.dashboard"))
        flash("Invalid login details.", "danger")
    return render_template("auth/login.html")

@auth.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.home"))

@customer.route("/dashboard")
@roles_required("customer")
def dashboard():
    orders = Order.query.filter_by(customer_id=current_user.id).order_by(Order.created_at.desc()).limit(10).all()
    active = Order.query.filter(Order.customer_id == current_user.id,
        Order.status.notin_(["Delivered", "Cancelled"])).count()
    return render_template("customer/dashboard.html", orders=orders, active=active)

@customer.route("/book", methods=["GET", "POST"])
@roles_required("customer")
def book():
    services = Service.query.filter_by(active=True).order_by(Service.name).all()
    if request.method == "POST":
        ids, quantities = request.form.getlist("service_id"), request.form.getlist("quantity")
        garments, custom_garments = request.form.getlist("garment"), request.form.getlist("custom_garment")
        if not ids:
            flash("Choose at least one service.", "danger")
            return render_template("customer/book.html", services=services, garments=GARMENTS)
        instruction_photos = [f for f in request.files.getlist("photos") if f and f.filename]
        if len(instruction_photos) > 5 or any(not validate_photo(f) for f in instruction_photos):
            flash("Choose up to 5 JPG, PNG, or WebP instruction photos.", "danger")
            return render_template("customer/book.html", services=services, garments=GARMENTS)
        order = Order(order_number="ASE-" + secrets.token_hex(4).upper(),
            customer_id=current_user.id, created_by_id=current_user.id,
            booking_source="Online", pickup_address=request.form.get("pickup_address", "").strip(),
            notes=request.form.get("notes", "").strip(),
            pickup_latitude=request.form.get("pickup_latitude", type=float),
            pickup_longitude=request.form.get("pickup_longitude", type=float))
        db.session.add(order)
        db.session.flush()
        total = Decimal("0.00")
        try:
            for sid, qty, garment, custom_garment in zip(ids, quantities, garments, custom_garments):
                service = db.session.get(Service, int(sid))
                quantity = int(qty)
                if not service or not service.active or quantity < 1 or quantity > 500:
                    raise ValueError()
                price = Decimal(str(service.price))
                subtotal = price * quantity
                total += subtotal
                garment_name = custom_garment.strip() if garment == "Other" else garment.strip()
                if not garment_name:
                    raise ValueError()
                db.session.add(OrderItem(order_id=order.id, service_id=service.id,
                    garment=garment_name or service.name, quantity=quantity,
                    unit_price=price, subtotal=subtotal))
        except (ValueError, InvalidOperation):
            db.session.rollback()
            flash("Please check the selected services and quantities.", "danger")
            return render_template("customer/book.html", services=services, garments=GARMENTS)
        order.total_amount = total
        db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
            status="Pending", note="Online booking received"))
        _fill_unassigned()
        if instruction_photos:
            for uploaded in instruction_photos:
                filename = save_private_photo(uploaded)
                db.session.add(OrderPhoto(order_id=order.id, filename=filename))
            db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
                status=order.status, note=f"Customer uploaded {len(instruction_photos)} instruction photo(s)"))
        db.session.commit()
        flash("Your booking has been received.", "success")
        return redirect(url_for("customer.dashboard"))
    return render_template("customer/book.html", services=services, garments=GARMENTS)

@customer.route("/orders/<int:order_id>/location", methods=["POST"])
@roles_required("customer")
def update_location(order_id):
    order = Order.query.filter_by(id=order_id, customer_id=current_user.id).first_or_404()
    latitude = request.form.get("latitude", type=float)
    longitude = request.form.get("longitude", type=float)
    if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        flash("Could not read your current location. Please try again.", "danger")
        return redirect(url_for("customer.order_detail", order_id=order.id))
    order.pickup_latitude, order.pickup_longitude = latitude, longitude
    db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
        status=order.status, note="Customer updated the pickup location"))
    db.session.commit()
    flash("Pickup location updated.", "success")
    return redirect(url_for("customer.order_detail", order_id=order.id))

@customer.route("/orders/<int:order_id>")
@roles_required("customer")
def order_detail(order_id):
    order = Order.query.filter_by(id=order_id, customer_id=current_user.id).first_or_404()
    history = StatusHistory.query.filter_by(order_id=order.id).order_by(StatusHistory.created_at).all()
    return render_template("customer/order_detail.html", order=order, history=history)

@customer.route("/orders/<int:order_id>/photos", methods=["POST"])
@roles_required("customer")
def upload_order_photos(order_id):
    order = Order.query.filter_by(id=order_id, customer_id=current_user.id).first_or_404()
    files = [f for f in request.files.getlist("photos") if f and f.filename]
    if not files or len(files) > 5 or any(not validate_photo(f) for f in files):
        flash("Choose up to 5 JPG, PNG, or WebP photos.", "danger")
        return redirect(url_for("customer.order_detail", order_id=order.id))
    for uploaded in files:
        filename = save_private_photo(uploaded)
        db.session.add(OrderPhoto(order_id=order.id, filename=filename))
    db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
        status=order.status, note=f"Customer uploaded {len(files)} instruction photo(s)"))
    db.session.commit()
    flash("Instruction photos added to your order.", "success")
    return redirect(url_for("customer.order_detail", order_id=order.id))

@customer.route("/orders/<int:order_id>/photos/<int:photo_id>")
@roles_required("customer", "admin", "staff", "delivery_agent")
def order_photo(order_id, photo_id):
    order = db.session.get(Order, order_id) or abort(404)
    photo = OrderPhoto.query.filter_by(id=photo_id, order_id=order.id).first_or_404()
    allowed = (
        current_user.role == "admin"
        or (current_user.role == "customer" and order.customer_id == current_user.id)
        or (current_user.role == "staff" and order.assigned_staff_id == current_user.id)
        or (current_user.role == "delivery_agent" and order.delivery_agent_id == current_user.id)
    )
    if not allowed:
        abort(403)
    return send_from_directory(photo_folder(), photo.filename, as_attachment=False, max_age=0)

@admin.route("/dashboard")
@roles_required("admin")
def dashboard():
    total = Order.query.count()
    active = Order.query.filter(Order.status.notin_(["Delivered", "Cancelled"])).count()
    revenue = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter_by(status="Paid").scalar()
    recent = Order.query.order_by(Order.created_at.desc()).limit(8).all()
    staff_members = User.query.filter_by(role="staff").all()
    delivery_agents = User.query.filter_by(role="delivery_agent").all()
    status_options = {o.id: next_statuses(o, "admin") for o in recent}
    return render_template("admin/dashboard.html", total=total, active=active, revenue=revenue, recent=recent, statuses=STATUSES, status_options=status_options, staff_members=staff_members, delivery_agents=delivery_agents)

@admin.route("/orders")
@roles_required("admin")
def orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    staff_members = User.query.filter_by(role="staff").all()
    delivery_agents = User.query.filter_by(role="delivery_agent").all()
    status_options = {o.id: next_statuses(o, "admin") for o in orders}
    return render_template("admin/orders.html", orders=orders, statuses=STATUSES, status_options=status_options, staff_members=staff_members, delivery_agents=delivery_agents)

@admin.route("/walk-in", methods=["GET", "POST"])
@roles_required("admin")
def walk_in():
    services = Service.query.filter_by(active=True).order_by(Service.name).all()
    if request.method == "POST":
        name, phone = request.form.get("customer_name", "").strip(), request.form.get("phone", "").strip()
        service = db.session.get(Service, request.form.get("service_id", type=int))
        quantity = request.form.get("quantity", type=int)
        if not name or not valid_phone(phone) or not service or not quantity or quantity < 1:
            flash("Complete all required fields with a valid phone number (7–15 digits, optional leading +).", "danger")
            return render_template("admin/walk_in.html", services=services)
        user = User.query.filter_by(phone=phone).first()
        if not user:
            user = User(name=name, phone=phone, role="customer")
            user.set_password(secrets.token_urlsafe(18))
            db.session.add(user)
            db.session.flush()
        amount = Decimal(str(service.price)) * quantity
        order = Order(order_number="ASE-" + secrets.token_hex(4).upper(),
            customer_id=user.id, created_by_id=current_user.id, booking_source="Walk-in", status="Received")
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, service_id=service.id,
            garment=request.form.get("garment", "").strip() or service.name,
            quantity=quantity, unit_price=service.price, subtotal=amount))
        order.total_amount = amount
        db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
            status="Received", note="Walk-in order created"))
        _fill_unassigned()
        db.session.commit()
        flash("Walk-in order created: " + order.order_number, "success")
        return redirect(url_for("admin.orders"))
    return render_template("admin/walk_in.html", services=services)

@admin.route("/orders/<int:order_id>/status", methods=["POST"])
@roles_required("admin", "staff")
def update_status(order_id):
    order = db.session.get(Order, order_id) or abort(404)
    if current_user.role == "staff" and order.assigned_staff_id != current_user.id:
        abort(403)
    status = request.form.get("status")
    if status not in next_statuses(order, current_user.role):
        abort(400, description="That order status transition is not allowed.")
    order.status = status
    db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
        status=status, note=request.form.get("note", "")))
    _fill_unassigned()
    db.session.commit()
    flash("Order status updated.", "success")
    return redirect(request.referrer or url_for("admin.orders"))

@admin.route("/services", methods=["GET", "POST"])
@roles_required("admin")
def services():
    if request.method == "POST":
        service_id = request.form.get("service_id", type=int)
        name = request.form.get("name", "").strip()
        name_ml = request.form.get("name_ml", "").strip()
        unit = request.form.get("unit", "piece")
        try:
            price = Decimal(request.form.get("price", "0"))
            if price < 0 or not name:
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            flash("Enter a service name and valid price.", "danger")
            return redirect(url_for("admin.services"))
        service = db.session.get(Service, service_id) if service_id else Service()
        service.name, service.name_ml, service.unit, service.price = name, name_ml, unit, price
        service.active = True
        db.session.add(service)
        db.session.commit()
        flash("Service and price saved.", "success")
        return redirect(url_for("admin.services"))
    return render_template("admin/services.html", services=Service.query.order_by(Service.id).all())

@admin.route("/payments", methods=["GET", "POST"])
@roles_required("admin")
def payments():
    if request.method == "POST":
        order = Order.query.filter_by(id=request.form.get("order_id", type=int)).with_for_update().first()
        try:
            amount = Decimal(request.form.get("amount", "0"))
            if not order or amount <= 0:
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            flash("Select an order and enter a valid amount.", "danger")
            return redirect(url_for("admin.payments"))
        paid = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter_by(order_id=order.id, status="Paid").scalar()
        balance = max(Decimal("0.00"), Decimal(str(order.total_amount)) - Decimal(str(paid)))
        if amount > balance:
            db.session.rollback()
            flash(f"Payment exceeds the remaining balance of ₹{balance:.2f}.", "danger")
            return redirect(url_for("admin.payments"))
        db.session.add(Payment(order_id=order.id, amount=amount,
            method=request.form.get("method", "Cash"), status="Paid"))
        db.session.commit()
        flash("Payment recorded.", "success")
        return redirect(url_for("admin.payments"))
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template("admin/payments.html", orders=orders)

@admin.route("/team", methods=["GET", "POST"])
@roles_required("admin")
def team():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower() or None
        role = request.form.get("role", "")
        password = request.form.get("password", "")
        if role not in ("staff", "delivery_agent") or not name or not valid_phone(phone) or len(password) < 8:
            flash("Enter valid details and a phone number with 7–15 digits (optional leading +). Password must be at least 8 characters.", "danger")
            return redirect(url_for("admin.team"))
        if User.query.filter_by(phone=phone).first() or (email and User.query.filter_by(email=email).first()):
            flash("Phone number or email is already registered.", "danger")
            return redirect(url_for("admin.team"))
        person = User(name=name, phone=phone, email=email, role=role)
        person.set_password(password)
        db.session.add(person)
        db.session.commit()
        flash(f"{role.replace('_', ' ').title()} account created.", "success")
        return redirect(url_for("admin.team"))
    people = User.query.filter(User.role.in_(["staff", "delivery_agent"])).order_by(User.name).all()
    return render_template("admin/team.html", people=people)

@admin.route("/team/<int:user_id>/delete", methods=["POST"])
@roles_required("admin")
def delete_team_member(user_id):
    person = User.query.filter(User.id == user_id, User.role.in_(["staff", "delivery_agent"])).first_or_404()
    role, label = person.role, "laundry staff" if person.role == "staff" else "delivery agent"
    affected = Order.query.filter((Order.assigned_staff_id == person.id) if role == "staff" else
        (Order.delivery_agent_id == person.id)).all()
    # Preserve historical attribution before deleting the account.
    StatusHistory.query.filter_by(updated_by_id=person.id).update({"updated_by_id": current_user.id})
    for order in affected:
        if role == "staff":
            order.assigned_staff_id = None
        else:
            order.delivery_agent_id = None
        replacement = _free_team_member(role, exclude_id=person.id)
        if replacement:
            if role == "staff":
                order.assigned_staff_id = replacement.id
            else:
                order.delivery_agent_id = replacement.id
            db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
                status=order.status, note=f"Reassigned to {label} {replacement.name} after team account removal"))
        else:
            db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
                status=order.status, note=f"{label.title()} account removed; awaiting reassignment"))
    db.session.delete(person)
    db.session.flush()
    _fill_unassigned()
    db.session.commit()
    flash(f"{person.name}'s account was deleted and affected orders reassigned where a free team member was available.", "success")
    return redirect(url_for("admin.team"))

@admin.route("/orders/<int:order_id>/assign-staff", methods=["POST"])
@roles_required("admin")
def assign_staff(order_id):
    order = db.session.get(Order, order_id) or abort(404)
    staff_id = request.form.get("staff_id", type=int)
    person = db.session.get(User, staff_id) if staff_id else None
    if person and person.role != "staff":
        abort(400)
    previous = order.assigned_staff_id
    order.assigned_staff_id = person.id if person else None
    if previous != order.assigned_staff_id:
        db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
            status=order.status, note=f"Laundry staff assignment changed to {person.name if person else 'Unassigned'}"))
    _fill_unassigned()
    db.session.commit()
    flash("Laundry staff assignment saved.", "success")
    return redirect(url_for("admin.orders"))

@admin.route("/orders/<int:order_id>/assign-delivery", methods=["POST"])
@roles_required("admin")
def assign_delivery(order_id):
    order = db.session.get(Order, order_id) or abort(404)
    agent_id = request.form.get("agent_id", type=int)
    agent = db.session.get(User, agent_id) if agent_id else None
    if agent and agent.role != "delivery_agent":
        abort(400)
    previous = order.delivery_agent_id
    order.delivery_agent_id = agent.id if agent else None
    if previous != order.delivery_agent_id:
        db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
            status=order.status, note=f"Delivery assignment changed to {agent.name if agent else 'Unassigned'}"))
    _fill_unassigned()
    db.session.commit()
    flash("Delivery agent assignment saved.", "success")
    return redirect(url_for("admin.orders"))

@staff.route("/dashboard")
@roles_required("staff")
def dashboard():
    orders = Order.query.filter_by(assigned_staff_id=current_user.id).order_by(Order.created_at.desc()).all()
    completed = sum(o.status in STAFF_DONE_STATUSES for o in orders)
    active = len(orders) - completed
    status_options = {o.id: next_statuses(o, "staff") for o in orders}
    return render_template("staff/dashboard.html", orders=orders, statuses=STATUSES, status_options=status_options, completed=completed, active=active)

@delivery.route("/dashboard")
@roles_required("delivery_agent")
def dashboard():
    orders = Order.query.filter_by(delivery_agent_id=current_user.id).order_by(Order.created_at.desc()).all()
    completed = sum(o.status == "Delivered" for o in orders)
    active = sum(o.status not in DONE_STATUSES for o in orders)
    status_options = {o.id: next_statuses(o, "delivery_agent") for o in orders}
    return render_template("delivery/dashboard.html", orders=orders, statuses=STATUSES, status_options=status_options, completed=completed, active=active)

@delivery.route("/orders/<int:order_id>/status", methods=["POST"])
@roles_required("delivery_agent")
def update_delivery_status(order_id):
    order = Order.query.filter_by(id=order_id, delivery_agent_id=current_user.id).first_or_404()
    status = request.form.get("status")
    if status not in next_statuses(order, "delivery_agent"):
        abort(400, description="That delivery status transition is not allowed.")
    order.status = status
    db.session.add(StatusHistory(order_id=order.id, updated_by_id=current_user.id,
        status=status, note="Delivery agent update"))
    _fill_unassigned()
    db.session.commit()
    flash("Delivery status updated.", "success")
    return redirect(url_for("delivery.dashboard"))
