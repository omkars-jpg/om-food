# FoodHub by Soni v2 - Flask + SQLAlchemy (simple, commented code)
import os
import random
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
db_url = os.environ.get("DATABASE_URL", "sqlite:///foodhub.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db = SQLAlchemy(app)

STATUSES = ["Placed", "Preparing", "Out for Delivery", "Delivered"]
# coupon code : (discount percent, max discount in Rs, minimum order in Rs)
COUPONS = {"FOOD20": (20, 100, 299), "SONI10": (10, 50, 149), "BIGDEAL": (30, 200, 599)}


# ---------- DATABASE TABLES ----------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)


class Restaurant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    cuisine = db.Column(db.String(60), nullable=False)
    emoji = db.Column(db.String(8), default="🍽️")
    rating = db.Column(db.Float, default=4.0)
    eta = db.Column(db.Integer, default=30)
    dishes = db.relationship("Dish", backref="restaurant")
    reviews = db.relationship("Review", backref="restaurant")


class Dish(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurant.id"))
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    is_veg = db.Column(db.Boolean, default=True)
    emoji = db.Column(db.String(8), default="🍛")


class Review(db.Model):  # naya table
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurant.id"))
    name = db.Column(db.String(80))
    stars = db.Column(db.Integer)
    text = db.Column(db.String(300))


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurant.id"))
    address = db.Column(db.String(255))
    phone = db.Column(db.String(20))
    total = db.Column(db.Integer)
    status = db.Column(db.String(30), default="Placed")
    created = db.Column(db.DateTime, server_default=db.func.now())
    items = db.relationship("OrderItem", backref="order")
    bill = db.relationship("Bill", uselist=False)
    restaurant = db.relationship("Restaurant")
    user = db.relationship("User")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"))
    name = db.Column(db.String(100))
    price = db.Column(db.Integer)
    qty = db.Column(db.Integer)


class Bill(db.Model):  # naya table: invoice ka poora hisaab
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"))
    subtotal = db.Column(db.Integer)
    discount = db.Column(db.Integer)
    fee = db.Column(db.Integer)
    tax = db.Column(db.Integer)
    total = db.Column(db.Integer)
    coupon = db.Column(db.String(20))


with app.app_context():
    db.create_all()


# ---------- HELPERS ----------
def current_user():
    uid = session.get("user_id")
    if uid:
        return db.session.get(User, uid)
    return None


def get_cart():
    return session.get("cart", {"restaurant_id": None, "items": {}})


def calc_bill(subtotal, code):
    # discount -> delivery fee -> 5% GST (discount ke baad) -> total
    discount = 0
    if code in COUPONS:
        percent, max_off, min_order = COUPONS[code]
        if subtotal >= min_order:
            discount = min(round(subtotal * percent / 100), max_off)
    fee = 0
    if 0 < subtotal < 500:
        fee = 30
    tax = round((subtotal - discount) * 0.05)
    total = subtotal - discount + fee + tax
    return {"discount": discount, "fee": fee, "tax": tax, "total": total}


def cart_details():
    lines = []
    subtotal = 0
    for dish_id, qty in get_cart()["items"].items():
        dish = db.session.get(Dish, int(dish_id))
        if dish:
            lines.append({"dish": dish, "qty": qty, "total": dish.price * qty})
            subtotal = subtotal + dish.price * qty
    return lines, subtotal, calc_bill(subtotal, session.get("coupon", ""))


@app.context_processor
def inject_globals():
    count = 0
    qty_map = {}
    for key, qty in get_cart()["items"].items():
        count = count + qty
        qty_map[int(key)] = qty
    return {"user": current_user(), "cart_count": count, "cart_qty": qty_map}


# ---------- CUSTOMER PAGES ----------
@app.route("/")
def home():
    q = request.args.get("q", "").strip()
    cuisine = request.args.get("cuisine", "").strip()
    sort = request.args.get("sort", "rating")
    minr = request.args.get("minr", "")
    query = Restaurant.query
    if q:
        like = "%" + q + "%"
        # restaurant ka naam, cuisine ya dish ka naam - kisi se bhi match
        dish_match = db.session.query(Dish.restaurant_id).filter(Dish.name.ilike(like))
        query = query.filter(or_(Restaurant.name.ilike(like),
                                 Restaurant.cuisine.ilike(like),
                                 Restaurant.id.in_(dish_match)))
    if cuisine:
        query = query.filter(Restaurant.cuisine == cuisine)
    if minr:
        query = query.filter(Restaurant.rating >= float(minr))
    if sort == "eta":
        query = query.order_by(Restaurant.eta)
    elif sort == "name":
        query = query.order_by(Restaurant.name)
    else:
        query = query.order_by(Restaurant.rating.desc())
    cuisines = []
    for r in Restaurant.query.order_by(Restaurant.cuisine).all():
        if r.cuisine not in cuisines:
            cuisines.append(r.cuisine)
    return render_template("index.html", restaurants=query.all(), cuisines=cuisines,
                           q=q, cuisine=cuisine, sort=sort, minr=minr)


@app.route("/restaurant/<int:rid>")
def restaurant(rid):
    r = db.get_or_404(Restaurant, rid)
    only_veg = request.args.get("veg") == "1"
    dishes = []
    for d in r.dishes:
        if d.is_veg or not only_veg:
            dishes.append(d)
    return render_template("restaurant.html", r=r, dishes=dishes, only_veg=only_veg)


@app.route("/restaurant/<int:rid>/review", methods=["POST"])
def add_review(rid):
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    r = db.get_or_404(Restaurant, rid)
    db.session.add(Review(restaurant_id=rid, name=user.name,
                          stars=int(request.form["stars"]), text=request.form["text"][:300]))
    db.session.flush()
    total = 0
    all_reviews = Review.query.filter_by(restaurant_id=rid).all()
    for rv in all_reviews:
        total = total + rv.stars
    r.rating = round(total / len(all_reviews), 1)  # average rating update
    db.session.commit()
    return redirect(url_for("restaurant", rid=rid))


@app.route("/cart")
def cart():
    lines, subtotal, bill = cart_details()
    return render_template("cart.html", lines=lines, subtotal=subtotal, bill=bill,
                           coupon=session.get("coupon", ""), coupons=COUPONS)


@app.route("/cart/add/<int:dish_id>", methods=["POST"])
def cart_add(dish_id):
    dish = db.get_or_404(Dish, dish_id)
    cart_data = get_cart()
    if cart_data["items"] and cart_data["restaurant_id"] != dish.restaurant_id:
        cart_data = {"restaurant_id": None, "items": {}}
        flash("Cart clear ho gaya: ek time pe ek hi restaurant se order hota hai.")
    cart_data["restaurant_id"] = dish.restaurant_id
    key = str(dish_id)
    cart_data["items"][key] = cart_data["items"].get(key, 0) + 1
    session["cart"] = cart_data
    return redirect(request.referrer or url_for("home"))


@app.route("/cart/remove/<int:dish_id>", methods=["POST"])
def cart_remove(dish_id):
    cart_data = get_cart()
    key = str(dish_id)
    if key in cart_data["items"]:
        cart_data["items"][key] = cart_data["items"][key] - 1
        if cart_data["items"][key] <= 0:
            del cart_data["items"][key]
    session["cart"] = cart_data
    return redirect(request.referrer or url_for("cart"))


@app.route("/cart/coupon", methods=["POST"])
def cart_coupon():
    code = request.form["code"].strip().upper()
    lines, subtotal, bill = cart_details()
    if code not in COUPONS:
        flash("Ye coupon code galat hai.")
    elif subtotal < COUPONS[code][2]:
        flash("Is coupon ke liye minimum order Rs " + str(COUPONS[code][2]) + " hona chahiye.")
    else:
        session["coupon"] = code
        flash("Coupon " + code + " lag gaya!")
    return redirect(url_for("cart"))


@app.route("/cart/coupon/remove", methods=["POST"])
def cart_coupon_remove():
    session.pop("coupon", None)
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["POST"])
def checkout():
    user = current_user()
    if not user:
        flash("Order karne ke liye pehle login karo.")
        return redirect(url_for("login"))
    lines, subtotal, bill = cart_details()
    if not lines:
        return redirect(url_for("cart"))
    order = Order(user_id=user.id, restaurant_id=get_cart()["restaurant_id"],
                  address=request.form["address"], phone=request.form["phone"],
                  total=bill["total"])
    db.session.add(order)
    db.session.flush()
    for line in lines:
        db.session.add(OrderItem(order_id=order.id, name=line["dish"].name,
                                 price=line["dish"].price, qty=line["qty"]))
    db.session.add(Bill(order_id=order.id, subtotal=subtotal, discount=bill["discount"],
                        fee=bill["fee"], tax=bill["tax"], total=bill["total"],
                        coupon=session.get("coupon", "")))
    db.session.commit()
    session.pop("cart", None)
    session.pop("coupon", None)
    return redirect(url_for("order_detail", oid=order.id))


@app.route("/orders")
def orders():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    my = Order.query.filter_by(user_id=user.id).order_by(Order.id.desc()).all()
    return render_template("orders.html", orders=my)


@app.route("/order/<int:oid>")
def order_detail(oid):
    user = current_user()
    order = db.get_or_404(Order, oid)
    if not user or (order.user_id != user.id and not user.is_admin):
        return redirect(url_for("login"))
    return render_template("order.html", order=order, statuses=STATUSES)


# ---------- LOGIN / REGISTER ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        if User.query.filter_by(email=email).first():
            flash("Ye email pehle se registered hai.")
        else:
            admin_email = os.environ.get("ADMIN_EMAIL", "").lower()
            u = User(name=request.form["name"], email=email,
                     password_hash=generate_password_hash(request.form["password"]),
                     is_admin=(email == admin_email))
            db.session.add(u)
            db.session.commit()
            session["user_id"] = u.id
            return redirect(url_for("home"))
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(email=request.form["email"].strip().lower()).first()
        if u and check_password_hash(u.password_hash, request.form["password"]):
            session["user_id"] = u.id
            return redirect(url_for("home"))
        flash("Email ya password galat hai.")
    return render_template("auth.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ---------- ADMIN PANEL ----------
def is_admin():
    u = current_user()
    return bool(u and u.is_admin)


@app.route("/admin")
def admin():
    if not is_admin():
        return redirect(url_for("login"))
    return render_template("admin.html", orders=Order.query.order_by(Order.id.desc()).all(),
                           restaurants=Restaurant.query.all(), statuses=STATUSES)


@app.route("/admin/order/<int:oid>", methods=["POST"])
def admin_order(oid):
    if is_admin():
        db.get_or_404(Order, oid).status = request.form["status"]
        db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/restaurant", methods=["POST"])
def admin_restaurant():
    if is_admin():
        db.session.add(Restaurant(name=request.form["name"], cuisine=request.form["cuisine"],
                                  emoji=request.form["emoji"] or "🍽️"))
        db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/dish", methods=["POST"])
def admin_dish():
    if is_admin():
        db.session.add(Dish(restaurant_id=int(request.form["restaurant_id"]),
                            name=request.form["name"], price=int(request.form["price"]),
                            is_veg=(request.form["veg"] == "1"),
                            emoji=request.form["emoji"] or "🍛"))
        db.session.commit()
    return redirect(url_for("admin"))


# ---------- DEMO DATA (20 restaurants, 48 dishes, reviews) ----------
# cuisine : list of (dish name, price, is_veg, emoji)
MENUS = {
    "North Indian": [("Paneer Butter Masala", 220, True, "🧀"), ("Butter Chicken", 290, False, "🍗"),
                     ("Dal Makhani", 180, True, "🍲"), ("Garlic Naan", 55, True, "🫓"),
                     ("Chicken Tikka", 260, False, "🍢"), ("Jeera Rice", 120, True, "🍚")],
    "South Indian": [("Masala Dosa", 110, True, "🥞"), ("Idli Sambar", 80, True, "🍥"),
                     ("Medu Vada", 70, True, "🍩"), ("Uttapam", 120, True, "🥞"),
                     ("Chicken Chettinad", 250, False, "🍗"), ("Filter Coffee", 50, True, "☕")],
    "Chinese": [("Veg Hakka Noodles", 150, True, "🍜"), ("Chicken Manchurian", 210, False, "🍢"),
                ("Veg Fried Rice", 140, True, "🍚"), ("Chilli Paneer", 190, True, "🌶️"),
                ("Schezwan Chicken", 230, False, "🍗"), ("Veg Spring Rolls", 120, True, "🥟")],
    "Pizza": [("Margherita Pizza", 249, True, "🍕"), ("Farmhouse Pizza", 329, True, "🍕"),
              ("Chicken Tikka Pizza", 369, False, "🍕"), ("Garlic Bread", 129, True, "🥖"),
              ("Pasta Alfredo", 219, True, "🍝"), ("Choco Lava Cake", 99, True, "🍰")],
    "Burgers": [("Aloo Tikki Burger", 89, True, "🍔"), ("Veg Cheese Burger", 129, True, "🍔"),
                ("Chicken Zinger Burger", 169, False, "🍔"), ("French Fries", 99, True, "🍟"),
                ("Chicken Nuggets", 149, False, "🍗"), ("Chocolate Shake", 130, True, "🥤")],
    "Biryani": [("Chicken Dum Biryani", 260, False, "🍛"), ("Mutton Biryani", 340, False, "🍛"),
                ("Veg Biryani", 190, True, "🍛"), ("Egg Biryani", 210, False, "🥚"),
                ("Chicken 65", 220, False, "🍗"), ("Raita", 40, True, "🥣")],
    "Desserts": [("Chocolate Truffle Cake", 320, True, "🎂"), ("Gulab Jamun", 80, True, "🍮"),
                 ("Rasmalai", 110, True, "🍨"), ("Brownie with Ice Cream", 150, True, "🍫"),
                 ("Kulfi Falooda", 120, True, "🍧"), ("Cold Coffee", 110, True, "🥤")],
    "Healthy": [("Greek Salad Bowl", 199, True, "🥗"), ("Grilled Chicken Bowl", 279, False, "🍗"),
                ("Quinoa Veg Bowl", 229, True, "🥙"), ("Fruit Smoothie", 140, True, "🥤"),
                ("Paneer Wrap", 169, True, "🌯"), ("Oats Porridge", 120, True, "🥣")],
}
RESTAURANTS = [
    ("Spice Garden", "North Indian", "🍛"), ("Punjabi Tadka", "North Indian", "🍗"),
    ("Royal Darbar", "North Indian", "🫓"), ("Dosa Corner", "South Indian", "🥞"),
    ("Udupi Delight", "South Indian", "🍥"), ("Madras Cafe", "South Indian", "☕"),
    ("Dragon Bowl", "Chinese", "🥡"), ("Wok Express", "Chinese", "🍜"),
    ("China Town Kitchen", "Chinese", "🥟"), ("Pizza Point", "Pizza", "🍕"),
    ("Slice House", "Pizza", "🍕"), ("Burger Barn", "Burgers", "🍔"),
    ("Patty Lab", "Burgers", "🍟"), ("Biryani Junction", "Biryani", "🍛"),
    ("Hyderabadi Handi", "Biryani", "🍲"), ("Dum Pukht House", "Biryani", "🍗"),
    ("Sweet Tooth", "Desserts", "🍰"), ("Cake Walk", "Desserts", "🎂"),
    ("Green Bowl", "Healthy", "🥗"), ("Fit Kitchen", "Healthy", "🥙"),
]
REVIEW_NAMES = ["Aarav", "Priya", "Rohan", "Sneha", "Vikram", "Ananya", "Karan", "Meera", "Rahul", "Isha"]
REVIEW_TEXTS = [
    (5, "Bahut tasty khana, delivery bhi time pe aayi!"), (5, "Best in the area, portion size zabardast."),
    (5, "Packing ekdum neat, khana garam pahuncha."), (4, "Taste accha tha, thoda spicy tha."),
    (4, "Value for money, will order again."), (4, "Quality achhi hai, delivery thodi late thi."),
    (3, "Theek-thaak, ek baar try kar sakte ho."), (3, "Khana okay tha, price thoda zyada laga."),
]


@app.route("/setup")
def setup():
    if request.args.get("key") != os.environ.get("SETUP_KEY", "soni123"):
        return "Wrong key", 403
    if request.args.get("reset") == "1":
        # purana demo data saaf (orders bhi delete honge)
        for model in [Bill, OrderItem, Order, Review, Dish, Restaurant]:
            model.query.delete()
        db.session.commit()
    if Restaurant.query.count() > 0:
        return "Data pehle se hai. Naya demo data chahiye to link ke end mein &reset=1 lagao."
    rnd = random.Random(42)  # har baar same demo data
    count = 0
    for name, cuisine, emoji in RESTAURANTS:
        count = count + 1
        r = Restaurant(name=name, cuisine=cuisine, emoji=emoji, eta=rnd.randint(20, 45))
        db.session.add(r)
        db.session.flush()
        for dname, price, veg, demoji in MENUS[cuisine]:
            # har restaurant ke rate thode alag
            db.session.add(Dish(restaurant_id=r.id, name=dname, price=price + (count % 4) * 10,
                                is_veg=veg, emoji=demoji))
        stars_total = 0
        for text_item in rnd.sample(REVIEW_TEXTS, 4):
            stars_total = stars_total + text_item[0]
            db.session.add(Review(restaurant_id=r.id, name=rnd.choice(REVIEW_NAMES),
                                  stars=text_item[0], text=text_item[1]))
        r.rating = round(stars_total / 4, 1)
    db.session.commit()
    return "Done! 20 restaurants ready. <a href='/'>Home</a>"


if __name__ == "__main__":
    app.run(debug=True)
