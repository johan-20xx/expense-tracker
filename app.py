from flask import Flask, render_template, request, redirect, session, Response
from flask_mysqldb import MySQL
import bcrypt, csv, io, random
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'expenseiq_secret_2026'
import os
app.config['MYSQL_HOST'] = os.environ.get('MYSQLHOST', 'localhost')
app.config['MYSQL_USER'] = os.environ.get('MYSQLUSER', 'root')
app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQLPASSWORD', 'your_local_password')
app.config['MYSQL_DB'] = os.environ.get('MYSQLDATABASE', 'expense_tracker')
app.config['MYSQL_PORT'] = int(os.environ.get('MYSQLPORT', 3306))
mysql = MySQL(app)
@app.context_processor
def inject_settings():
    return dict(settings=get_settings())
TIPS = [
    "Save before you spend — pay yourself first!",
    "Track every small expense. ₹10 here, ₹20 there adds up fast.",
    "The 24-hour rule: wait a day before any non-essential purchase.",
    "Cook at home once more per week and watch your Food budget drop.",
    "Review subscriptions monthly — cancel what you don't use.",
    "Needs vs wants — ask yourself before every purchase.",
    "Set a weekly spending limit and stick to it.",
    "Automate savings so you never have to think about it.",
]

def get_settings():
    if 'user_id' not in session:
        return {'currency': '₹', 'theme': 'light'}
    cur = mysql.connection.cursor()
    cur.execute("SELECT currency, theme FROM users WHERE id = %s", (session['user_id'],))
    u = cur.fetchone()
    cur.close()
    return {'currency': u[0] if u else '₹', 'theme': u[1] if u else 'light'}

@app.route('/')
def index():
    return redirect('/login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = bcrypt.hashpw(request.form['password'].encode('utf-8'), bcrypt.gensalt())
        cur = mysql.connection.cursor()
        try:
            cur.execute("INSERT INTO users (username, email, password) VALUES (%s,%s,%s)", (username, email, password))
            mysql.connection.commit()
            cur.close()
            return redirect('/login')
        except:
            cur.close()
            return render_template('register.html', error='Email already registered.')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password'].encode('utf-8')
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()
        if user and bcrypt.checkpw(password, user[3].encode('utf-8')):
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['tip'] = random.choice(TIPS)
            return redirect('/dashboard')
        return render_template('login.html', error='Invalid email or password.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    settings = get_settings()
    uid = session['user_id']
    now = datetime.now()
    month = int(request.args.get('month', now.month))
    year = int(request.args.get('year', now.year))
    cat_filter = request.args.get('category', 'all')
    cur = mysql.connection.cursor()

    # Filtered expenses
    if cat_filter != 'all':
        cur.execute("SELECT * FROM expenses WHERE user_id=%s AND MONTH(date)=%s AND YEAR(date)=%s AND category=%s ORDER BY date DESC",
                    (uid, month, year, cat_filter))
    else:
        cur.execute("SELECT * FROM expenses WHERE user_id=%s AND MONTH(date)=%s AND YEAR(date)=%s ORDER BY date DESC",
                    (uid, month, year))
    expenses = cur.fetchall()

    # All this month for charts
    cur.execute("SELECT * FROM expenses WHERE user_id=%s AND MONTH(date)=%s AND YEAR(date)=%s", (uid, month, year))
    all_exp = cur.fetchall()
    cat_totals = {}
    for e in all_exp:
        cat_totals[e[4]] = cat_totals.get(e[4], 0) + float(e[3])

    # Monthly trend (last 6 months)
    cur.execute("""SELECT MONTH(date), YEAR(date), SUM(amount) FROM expenses
                   WHERE user_id=%s GROUP BY YEAR(date), MONTH(date)
                   ORDER BY YEAR(date) DESC, MONTH(date) DESC LIMIT 6""", (uid,))
    trend_raw = list(reversed(cur.fetchall()))
    mnames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    trend_labels = [mnames[r[0]-1] + "'" + str(r[1])[-2:] for r in trend_raw]
    trend_values = [float(r[2]) for r in trend_raw]

    # Income
    cur.execute("SELECT SUM(amount) FROM income WHERE user_id=%s AND MONTH(date)=%s AND YEAR(date)=%s", (uid, month, year))
    income_total = float(cur.fetchone()[0] or 0)

    # Budget
    cur.execute("SELECT limit_amount FROM budgets WHERE user_id=%s AND month=%s AND year=%s", (uid, month, year))
    budget_row = cur.fetchone()
    budget = float(budget_row[0]) if budget_row else None

    # Last month
    lm = month - 1 if month > 1 else 12
    ly = year if month > 1 else year - 1
    cur.execute("SELECT SUM(amount) FROM expenses WHERE user_id=%s AND MONTH(date)=%s AND YEAR(date)=%s", (uid, lm, ly))
    last_total = float(cur.fetchone()[0] or 0)

    # Categories
    cur.execute("SELECT DISTINCT category FROM expenses WHERE user_id=%s", (uid,))
    categories = [r[0] for r in cur.fetchall()]
    cur.close()

    total = sum(float(e[3]) for e in expenses)
    savings = income_total - total if income_total else None
    most_spent = max(cat_totals, key=cat_totals.get) if cat_totals else None

    insights = []
    if cat_totals and total > 0:
        top = max(cat_totals, key=cat_totals.get)
        insights.append(f"You spent {(cat_totals[top]/total*100):.0f}% on {top} this month 🏷️")
    if last_total:
        diff = total - last_total
        if diff > 0:
            insights.append(f"You spent {settings['currency']}{abs(diff):.0f} more than last month 📈")
        elif diff < 0:
            insights.append(f"Great! You spent {settings['currency']}{abs(diff):.0f} less than last month 📉")
    if budget and total > budget:
        insights.append(f"⚠️ You've exceeded your {mnames[month-1]} budget!")
    elif budget and total >= budget * 0.8:
        insights.append(f"⚡ You've used {(total/budget*100):.0f}% of your {mnames[month-1]} budget.")

    return render_template('dashboard.html',
        expenses=expenses, username=session['username'],
        total=total, income_total=income_total, savings=savings,
        budget=budget, over_budget=(budget and total > budget),
        cat_labels=list(cat_totals.keys()),
        cat_values=[cat_totals[k] for k in cat_totals],
        trend_labels=trend_labels, trend_values=trend_values,
        insights=insights, categories=categories,
        cat_filter=cat_filter, month=month, year=year,
        most_spent=most_spent, tip=session.get('tip',''),
        settings=settings, mnames=mnames
    )

@app.route('/add', methods=['GET', 'POST'])
def add():
    if 'user_id' not in session: return redirect('/login')
    settings = get_settings()
    if request.method == 'POST':
        category = request.form['category']
        if category == 'Other':
            category = request.form.get('custom_category', 'Other')
        cur = mysql.connection.cursor()
        cur.execute("""INSERT INTO expenses (user_id,title,amount,category,date,notes,location,who_paid,is_recurring)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (session['user_id'], request.form['title'], request.form['amount'],
                     category, request.form['date'], request.form.get('notes',''),
                     request.form.get('location',''), request.form.get('who_paid',''),
                     1 if request.form.get('is_recurring') else 0))
        mysql.connection.commit()
        cur.close()
        return redirect('/dashboard')
    return render_template('add.html', settings=settings)

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    if 'user_id' not in session: return redirect('/login')
    settings = get_settings()
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        category = request.form['category']
        if category == 'Other':
            category = request.form.get('custom_category', 'Other')
        cur.execute("""UPDATE expenses SET title=%s,amount=%s,category=%s,date=%s,
                       notes=%s,location=%s,who_paid=%s,is_recurring=%s
                       WHERE id=%s AND user_id=%s""",
                    (request.form['title'], request.form['amount'], category,
                     request.form['date'], request.form.get('notes',''),
                     request.form.get('location',''), request.form.get('who_paid',''),
                     1 if request.form.get('is_recurring') else 0, id, session['user_id']))
        mysql.connection.commit()
        cur.close()
        return redirect('/dashboard')
    cur.execute("SELECT * FROM expenses WHERE id=%s AND user_id=%s", (id, session['user_id']))
    expense = cur.fetchone()
    cur.close()
    return render_template('edit.html', expense=expense, settings=settings)

@app.route('/delete/<int:id>')
def delete(id):
    if 'user_id' not in session: return redirect('/login')
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM expenses WHERE id=%s AND user_id=%s", (id, session['user_id']))
    mysql.connection.commit()
    cur.close()
    return redirect('/dashboard')

@app.route('/income', methods=['GET', 'POST'])
def income():
    if 'user_id' not in session: return redirect('/login')
    settings = get_settings()
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        cur.execute("INSERT INTO income (user_id,title,amount,source,date) VALUES (%s,%s,%s,%s,%s)",
                    (session['user_id'], request.form['title'], request.form['amount'],
                     request.form.get('source',''), request.form['date']))
        mysql.connection.commit()
    cur.execute("SELECT * FROM income WHERE user_id=%s ORDER BY date DESC", (session['user_id'],))
    incomes = cur.fetchall()
    cur.close()
    total = sum(float(i[3]) for i in incomes)
    return render_template('income.html', incomes=incomes, settings=settings, total=total)

@app.route('/delete_income/<int:id>')
def delete_income(id):
    if 'user_id' not in session: return redirect('/login')
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM income WHERE id=%s AND user_id=%s", (id, session['user_id']))
    mysql.connection.commit()
    cur.close()
    return redirect('/income')

@app.route('/budget', methods=['GET', 'POST'])
def budget():
    if 'user_id' not in session: return redirect('/login')
    settings = get_settings()
    now = datetime.now()
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        m, y, lim = request.form['month'], request.form['year'], request.form['limit_amount']
        cur.execute("SELECT id FROM budgets WHERE user_id=%s AND month=%s AND year=%s", (session['user_id'], m, y))
        if cur.fetchone():
            cur.execute("UPDATE budgets SET limit_amount=%s WHERE user_id=%s AND month=%s AND year=%s",
                        (lim, session['user_id'], m, y))
        else:
            cur.execute("INSERT INTO budgets (user_id,month,year,limit_amount) VALUES (%s,%s,%s,%s)",
                        (session['user_id'], m, y, lim))
        mysql.connection.commit()
    cur.execute("SELECT * FROM budgets WHERE user_id=%s ORDER BY year DESC, month DESC", (session['user_id'],))
    budgets = cur.fetchall()
    cur.close()
    mnames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    return render_template('budget.html', budgets=budgets, now=now, settings=settings, mnames=mnames)

@app.route('/goals', methods=['GET', 'POST'])
def goals():
    if 'user_id' not in session: return redirect('/login')
    settings = get_settings()
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            cur.execute("INSERT INTO savings_goals (user_id,title,target,saved,deadline) VALUES (%s,%s,%s,%s,%s)",
                        (session['user_id'], request.form['title'], request.form['target'],
                         request.form.get('saved', 0), request.form.get('deadline') or None))
        elif action == 'update':
            cur.execute("UPDATE savings_goals SET saved=%s WHERE id=%s AND user_id=%s",
                        (request.form['saved'], request.form['goal_id'], session['user_id']))
        elif action == 'delete':
            cur.execute("DELETE FROM savings_goals WHERE id=%s AND user_id=%s",
                        (request.form['goal_id'], session['user_id']))
        mysql.connection.commit()
    cur.execute("SELECT * FROM savings_goals WHERE user_id=%s", (session['user_id'],))
    goals_list = cur.fetchall()
    cur.close()
    return render_template('goals.html', goals=goals_list, settings=settings)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session: return redirect('/login')
    settings = get_settings()
    cur = mysql.connection.cursor()
    msg = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update':
            username = request.form['username']
            currency = request.form['currency']
            theme = request.form['theme']
            cur.execute("UPDATE users SET username=%s,currency=%s,theme=%s WHERE id=%s",
                        (username, currency, theme, session['user_id']))
            session['username'] = username
            msg = '✅ Profile updated!'
        elif action == 'password':
            old = request.form['old_password'].encode('utf-8')
            new = request.form['new_password'].encode('utf-8')
            cur.execute("SELECT password FROM users WHERE id=%s", (session['user_id'],))
            u = cur.fetchone()
            if u and bcrypt.checkpw(old, u[0].encode('utf-8')):
                cur.execute("UPDATE users SET password=%s WHERE id=%s",
                            (bcrypt.hashpw(new, bcrypt.gensalt()), session['user_id']))
                msg = '✅ Password changed!'
            else:
                msg = '❌ Old password is incorrect.'
        mysql.connection.commit()
    cur.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    return render_template('profile.html', user=user, settings=settings, msg=msg)

@app.route('/export')
def export():
    if 'user_id' not in session: return redirect('/login')
    cur = mysql.connection.cursor()
    cur.execute("SELECT title,amount,category,date,notes,location,who_paid FROM expenses WHERE user_id=%s ORDER BY date DESC",
                (session['user_id'],))
    rows = cur.fetchall()
    cur.close()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Title','Amount','Category','Date','Notes','Location','Who Paid'])
    for r in rows:
        w.writerow(r)
    out.seek(0)
    return Response(out, mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=my_expenses.csv'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)