from datetime import datetime
from decimal import Decimal
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db, login_manager

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer")
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    name_ml = db.Column(db.String(120))
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    unit = db.Column(db.String(30), nullable=False, default="piece")
    active = db.Column(db.Boolean, default=True)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(32), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    assigned_staff_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    delivery_agent_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    status = db.Column(db.String(30), nullable=False, default="Pending")
    booking_source = db.Column(db.String(20), nullable=False, default="Online")
    pickup_address = db.Column(db.Text)
    pickup_latitude = db.Column(db.Float)
    pickup_longitude = db.Column(db.Float)
    notes = db.Column(db.Text)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    customer = db.relationship("User", foreign_keys=[customer_id])
    assigned_staff = db.relationship("User", foreign_keys=[assigned_staff_id])
    delivery_agent = db.relationship("User", foreign_keys=[delivery_agent_id])
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")
    payments = db.relationship("Payment", backref="order", cascade="all, delete-orphan")

    @property
    def amount_paid(self):
        return sum((payment.amount for payment in self.payments if payment.status == "Paid"), Decimal("0.00"))

    @property
    def balance_due(self):
        return max(Decimal("0.00"), Decimal(str(self.total_amount)) - self.amount_paid)

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("service.id"), nullable=False)
    garment = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    service = db.relationship("Service")

class OrderPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    order = db.relationship("Order", backref=db.backref("photos", cascade="all, delete-orphan"))

class StatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.relationship("User")

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(db.String(30), default="Cash")
    status = db.Column(db.String(20), default="Paid")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
