from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from datetime import datetime, date, timedelta
from db import get_connection, init_db
import bcrypt

app = Flask(__name__)
app.secret_key = "habitflow_2026_secret"

init_db()

# ── helpers ───────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def time_status(start_time, end_time):
    """
    Returns: 'active', 'pending', or 'closed'
    Pure Python — no JavaScript needed.
    """
    if not start_time or not end_time:
        return "active"
    now = datetime.now()
    now_mins = now.hour * 60 + now.minute
    sh, sm = map(int, start_time.split(":"))
    eh, em = map(int, end_time.split(":"))
    start_mins = sh * 60 + sm
    end_mins   = eh * 60 + em
    if now_mins < start_mins:
        return "pending"
    elif now_mins > end_mins:
        return "closed"
    return "active"

def update_streak(cur, habit_id):
    cur.execute(
        "SELECT is_done FROM hf_habit_logs "
        "WHERE habit_id=:1 AND TRUNC(log_date)=TRUNC(SYSDATE)-1",
        [habit_id]
    )
    yesterday = cur.fetchone()
    was_done = yesterday and yesterday[0] == "Y"

    cur.execute(
        "SELECT current_streak, longest_streak, total_points "
        "FROM hf_streaks WHERE habit_id=:1", [habit_id]
    )
    row = cur.fetchone()
    if not row:
        return
    cur_s, long_s, pts = row

    cur_s = (cur_s + 1) if was_done else 1
    if cur_s > long_s:
        long_s = cur_s
    pts += 1
    if cur_s == 7:
        pts += 5
    elif cur_s == 30:
        pts += 20

    cur.execute(
        "UPDATE hf_streaks SET current_streak=:1, longest_streak=:2, "
        "total_points=:3 WHERE habit_id=:4",
        [cur_s, long_s, pts, habit_id]
    )

# ── auth ──────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET","POST"])
@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        conn = get_connection(); cur = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash FROM hf_users WHERE username=:1",
            [username]
        )
        user = cur.fetchone()
        cur.close(); conn.close()
        if user and bcrypt.checkpw(password.encode(), user[2].encode()):
            session["user_id"]  = user[0]
            session["username"] = user[1]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        confirm  = request.form.get("confirm","").strip()
        if not username or not password:
            flash("All fields required.", "danger")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        else:
            conn = get_connection(); cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM hf_users WHERE username=:1", [username]
            )
            if cur.fetchone()[0] > 0:
                flash("Username already taken.", "danger")
                cur.close(); conn.close()
            else:
                hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                cur.execute(
                    "INSERT INTO hf_users (username, password_hash) VALUES (:1,:2)",
                    [username, hashed]
                )
                conn.commit(); cur.close(); conn.close()
                flash("Account created! Please login.", "success")
                return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── dashboard ─────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    uid  = session["user_id"]
    conn = get_connection(); cur = conn.cursor()
    today = date.today()

    # ── Daily habits for today ────────────────────────────────────────────────
    cur.execute("""
        SELECT h.id, h.name, c.name, h.start_time, h.end_time,
               s.current_streak, s.total_points
        FROM hf_habits h
        LEFT JOIN hf_categories c ON h.category_id = c.id
        LEFT JOIN hf_streaks s    ON h.id = s.habit_id
        WHERE h.user_id=:1 AND h.habit_type='daily'
        AND h.status='active'
        AND TRUNC(h.start_date) <= TRUNC(SYSDATE)
        ORDER BY h.start_time NULLS LAST, h.id DESC
    """, [uid])
    daily_raw = cur.fetchall()

    daily_habits = []
    for row in daily_raw:
        hid = row[0]
        status = time_status(row[3], row[4])

        cur.execute(
            "SELECT is_done FROM hf_habit_logs "
            "WHERE habit_id=:1 AND TRUNC(log_date)=TRUNC(SYSDATE)", [hid]
        )
        log = cur.fetchone()
        is_done = log and log[0] == "Y"

        cur.execute("SELECT COUNT(*) FROM hf_sub_habits WHERE habit_id=:1", [hid])
        sub_count = cur.fetchone()[0]

        daily_habits.append({
            "id":             hid,
            "name":           row[1],
            "category":       row[2] or "General",
            "start_time":     row[3] or "",
            "end_time":       row[4] or "",
            "status":         status,
            "is_done":        is_done,
            "current_streak": row[5] or 0,
            "total_points":   row[6] or 0,
            "sub_count":      sub_count,
        })

    # ── Monthly habits ────────────────────────────────────────────────────────
    cur.execute("""
        SELECT h.id, h.name, c.name, h.start_date, h.end_date,
               s.current_streak, s.total_points
        FROM hf_habits h
        LEFT JOIN hf_categories c ON h.category_id = c.id
        LEFT JOIN hf_streaks s    ON h.id = s.habit_id
        WHERE h.user_id=:1 AND h.habit_type='monthly'
        AND h.status='active'
        ORDER BY h.start_date
    """, [uid])
    monthly_raw = cur.fetchall()

    monthly_habits = []
    for row in monthly_raw:
        hid = row[0]
        start_d = row[3]
        end_d   = row[4]

        # Count completed days
        cur.execute("""
            SELECT COUNT(*) FROM hf_habit_logs
            WHERE habit_id=:1 AND is_done='Y'
        """, [hid])
        done_days = cur.fetchone()[0]

        total_days = 30
        if start_d and end_d:
            delta = (end_d - start_d).days + 1
            total_days = max(delta, 1)

        # Is today done?
        cur.execute("""
            SELECT is_done FROM hf_habit_logs
            WHERE habit_id=:1 AND TRUNC(log_date)=TRUNC(SYSDATE)
        """, [hid])
        td = cur.fetchone()
        today_done = td and td[0] == "Y"

        if start_d and start_d.date() > today:
            m_status = "upcoming"
        elif end_d and end_d.date() < today:
            m_status = "ended"
        else:
            m_status = "active"

        progress_pct = int((done_days / total_days) * 100) if total_days else 0

        monthly_habits.append({
            "id":           hid,
            "name":         row[1],
            "category":     row[2] or "General",
            "start_date":   start_d.strftime("%b %d, %Y") if start_d else "",
            "end_date":     end_d.strftime("%b %d, %Y")   if end_d   else "",
            "done_days":    done_days,
            "total_days":   total_days,
            "progress_pct": progress_pct,
            "today_done":   today_done,
            "m_status":     m_status,
            "current_streak": row[5] or 0,
            "total_points":   row[6] or 0,
        })

    # ── Total points ──────────────────────────────────────────────────────────
    cur.execute("""
        SELECT NVL(SUM(s.total_points),0)
        FROM hf_streaks s JOIN hf_habits h ON s.habit_id=h.id
        WHERE h.user_id=:1
    """, [uid])
    total_points = cur.fetchone()[0]

    # ── Deleted streaks ───────────────────────────────────────────────────────
    cur.execute("""
        SELECT id, habit_name, streak_count, start_date, end_date, category_name
        FROM hf_deleted_streaks WHERE user_id=:1
        ORDER BY deleted_at DESC
    """, [uid])
    deleted_streaks = []
    for r in cur.fetchall():
        deleted_streaks.append({
            "id":          r[0],
            "habit_name":  r[1],
            "streak_count":r[2],
            "start_date":  r[3].strftime("%b %d, %Y") if r[3] else "",
            "end_date":    r[4].strftime("%b %d, %Y")  if r[4] else "",
            "category":    r[5] or "",
        })

    # ── Longest streaks ───────────────────────────────────────────────────────
    cur.execute("""
        SELECT h.name, s.longest_streak, s.current_streak
        FROM hf_streaks s JOIN hf_habits h ON s.habit_id=h.id
        WHERE h.user_id=:1 AND h.status='active'
        ORDER BY s.longest_streak DESC
        FETCH FIRST 5 ROWS ONLY
    """, [uid])
    top_streaks = cur.fetchall()

    cur.close(); conn.close()

    now_str = datetime.now().strftime("%I:%M %p")

    return render_template("dashboard.html",
        daily_habits=daily_habits,
        monthly_habits=monthly_habits,
        deleted_streaks=deleted_streaks,
        top_streaks=top_streaks,
        total_points=total_points,
        username=session["username"],
        now_str=now_str,
        today_str=date.today().strftime("%A, %B %d %Y"),
    )

# ── add habit ─────────────────────────────────────────────────────────────────

@app.route("/add_habit", methods=["GET","POST"])
@login_required
def add_habit():
    uid  = session["user_id"]
    conn = get_connection(); cur = conn.cursor()

    cur.execute("""
        SELECT id, name FROM hf_categories
        WHERE is_default='Y' OR user_id=:1
        ORDER BY is_default DESC, name
    """, [uid])
    categories = cur.fetchall()

    if request.method == "POST":
        habit_type  = request.form.get("habit_type","daily")
        name        = request.form.get("name","").strip()
        category_id = request.form.get("category_id") or None
        sub_habits  = [s.strip() for s in request.form.getlist("sub_habits[]") if s.strip()]

        if not name:
            flash("Habit name is required.", "danger")
            cur.close(); conn.close()
            return render_template("add_habit.html", categories=categories)

        if habit_type == "daily":
            start_time = request.form.get("start_time","").strip() or None
            end_time   = request.form.get("end_time","").strip()   or None
            start_date = date.today().strftime("%Y-%m-%d")

            cur.execute("""
                INSERT INTO hf_habits
                  (user_id, name, category_id, habit_type, start_time, end_time, start_date)
                VALUES (:1,:2,:3,'daily',:4,:5,TRUNC(SYSDATE))
            """, [uid, name, category_id, start_time, end_time])

        else:  # monthly
            start_date = request.form.get("start_date","").strip()
            duration   = int(request.form.get("duration", 30))
            if start_date:
                sd = datetime.strptime(start_date, "%Y-%m-%d").date()
                ed = sd + timedelta(days=duration - 1)
            else:
                sd = date.today()
                ed = sd + timedelta(days=29)

            cur.execute("""
                INSERT INTO hf_habits
                  (user_id, name, category_id, habit_type,
                   start_date, end_date)
                VALUES (:1,:2,:3,'monthly',
                  TO_DATE(:4,'YYYY-MM-DD'), TO_DATE(:5,'YYYY-MM-DD'))
            """, [uid, name, category_id,
                  sd.strftime("%Y-%m-%d"), ed.strftime("%Y-%m-%d")])

        # Get new habit id
        cur.execute(
            "SELECT MAX(id) FROM hf_habits WHERE user_id=:1", [uid]
        )
        habit_id = cur.fetchone()[0]

        for sh in sub_habits:
            cur.execute(
                "INSERT INTO hf_sub_habits (habit_id, name) VALUES (:1,:2)",
                [habit_id, sh]
            )

        cur.execute(
            "INSERT INTO hf_streaks (habit_id) VALUES (:1)", [habit_id]
        )

        conn.commit(); cur.close(); conn.close()
        flash(f'Habit "{name}" added!', "success")
        return redirect(url_for("dashboard"))

    cur.close(); conn.close()
    return render_template("add_habit.html", categories=categories)

# ── habit detail ──────────────────────────────────────────────────────────────

@app.route("/habit/<int:habit_id>", methods=["GET","POST"])
@login_required
def habit_detail(habit_id):
    uid  = session["user_id"]
    conn = get_connection(); cur = conn.cursor()

    cur.execute(
        "SELECT id, name, habit_type, start_time, end_time, status "
        "FROM hf_habits WHERE id=:1 AND user_id=:2",
        [habit_id, uid]
    )
    habit = cur.fetchone()
    if not habit:
        flash("Habit not found.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "mark_done":
            # Time window check for daily habits
            if habit[2] == "daily":
                ts = time_status(habit[3], habit[4])
                if ts == "pending":
                    flash("Time window has not opened yet. Come back later!", "warning")
                    return redirect(url_for("habit_detail", habit_id=habit_id))
                if ts == "closed":
                    flash("Time window is closed for today.", "danger")
                    return redirect(url_for("habit_detail", habit_id=habit_id))

            done_ids = request.form.getlist("sub_done[]")
            cur.execute(
                "SELECT id FROM hf_sub_habits WHERE habit_id=:1", [habit_id]
            )
            all_subs = [r[0] for r in cur.fetchall()]

            for sid in all_subs:
                is_done = "Y" if str(sid) in done_ids else "N"
                cur.execute("""
                    SELECT id FROM hf_sub_logs
                    WHERE sub_habit_id=:1 AND TRUNC(log_date)=TRUNC(SYSDATE)
                """, [sid])
                ex = cur.fetchone()
                if ex:
                    cur.execute(
                        "UPDATE hf_sub_logs SET is_done=:1 WHERE id=:2",
                        [is_done, ex[0]]
                    )
                else:
                    cur.execute(
                        "INSERT INTO hf_sub_logs (sub_habit_id, is_done) VALUES (:1,:2)",
                        [sid, is_done]
                    )

            if all_subs:
                full_done = "Y" if len(done_ids) == len(all_subs) else "N"
            else:
                full_done = "Y" if request.form.get("full_done") else "N"

            cur.execute("""
                SELECT id FROM hf_habit_logs
                WHERE habit_id=:1 AND TRUNC(log_date)=TRUNC(SYSDATE)
            """, [habit_id])
            ex_log = cur.fetchone()
            if ex_log:
                cur.execute(
                    "UPDATE hf_habit_logs SET is_done=:1 WHERE id=:2",
                    [full_done, ex_log[0]]
                )
            else:
                cur.execute(
                    "INSERT INTO hf_habit_logs (habit_id, is_done) VALUES (:1,:2)",
                    [habit_id, full_done]
                )

            if full_done == "Y":
                update_streak(cur, habit_id)

            conn.commit()
            flash("Progress saved!", "success")

        elif action == "delete":
            keep = request.form.get("keep_streak") == "yes"
            if keep:
                # Archive the streak before deleting
                cur.execute("""
                    SELECT s.current_streak, h.name, c.name,
                           h.start_date,
                           (SELECT MAX(log_date) FROM hf_habit_logs
                            WHERE habit_id=h.id AND is_done='Y') as last_done
                    FROM hf_habits h
                    LEFT JOIN hf_streaks s    ON h.id=s.habit_id
                    LEFT JOIN hf_categories c ON h.category_id=c.id
                    WHERE h.id=:1
                """, [habit_id])
                info = cur.fetchone()
                if info and info[0] and info[0] > 0:
                    cur.execute("""
                        INSERT INTO hf_deleted_streaks
                          (user_id, habit_name, streak_count,
                           start_date, end_date, category_name)
                        VALUES (:1,:2,:3,:4,:5,:6)
                    """, [uid, info[1], info[0],
                          info[3], info[4], info[2]])

            cur.execute(
                "UPDATE hf_habits SET status='deleted' WHERE id=:1", [habit_id]
            )
            conn.commit(); cur.close(); conn.close()
            flash("Habit deleted.", "info")
            return redirect(url_for("dashboard"))

    # GET — fetch detail
    cur.execute("""
        SELECT h.name, c.name, h.habit_type, h.start_time, h.end_time,
               h.start_date, h.end_date,
               s.current_streak, s.longest_streak, s.total_points
        FROM hf_habits h
        LEFT JOIN hf_categories c ON h.category_id=c.id
        LEFT JOIN hf_streaks s    ON h.id=s.habit_id
        WHERE h.id=:1
    """, [habit_id])
    info = cur.fetchone()

    cur.execute(
        "SELECT id, name FROM hf_sub_habits WHERE habit_id=:1", [habit_id]
    )
    sub_habits = cur.fetchall()

    done_today = set()
    for sh in sub_habits:
        cur.execute("""
            SELECT is_done FROM hf_sub_logs
            WHERE sub_habit_id=:1 AND TRUNC(log_date)=TRUNC(SYSDATE)
        """, [sh[0]])
        r = cur.fetchone()
        if r and r[0] == "Y":
            done_today.add(sh[0])

    cur.execute("""
        SELECT is_done FROM hf_habit_logs
        WHERE habit_id=:1 AND TRUNC(log_date)=TRUNC(SYSDATE)
    """, [habit_id])
    fl = cur.fetchone()
    is_fully_done = fl and fl[0] == "Y"

    ts = time_status(info[3], info[4]) if info[2] == "daily" else "active"

    cur.close(); conn.close()

    return render_template("habit_detail.html",
        habit_id=habit_id,
        habit_name=info[0],
        category=info[1] or "General",
        habit_type=info[2],
        start_time=info[3] or "",
        end_time=info[4]   or "",
        start_date=info[5].strftime("%b %d, %Y") if info[5] else "",
        end_date=info[6].strftime("%b %d, %Y")   if info[6] else "",
        current_streak=info[7] or 0,
        longest_streak=info[8] or 0,
        total_points=info[9]   or 0,
        sub_habits=sub_habits,
        done_today=done_today,
        is_fully_done=is_fully_done,
        time_status=ts,
        now_str=datetime.now().strftime("%I:%M %p"),
    )

# ── delete archived streak permanently ───────────────────────────────────────

@app.route("/delete_archived/<int:streak_id>", methods=["POST"])
@login_required
def delete_archived(streak_id):
    conn = get_connection(); cur = conn.cursor()
    cur.execute(
        "DELETE FROM hf_deleted_streaks WHERE id=:1 AND user_id=:2",
        [streak_id, session["user_id"]]
    )
    conn.commit(); cur.close(); conn.close()
    flash("Archived streak permanently deleted.", "info")
    return redirect(url_for("dashboard"))

# ── categories ────────────────────────────────────────────────────────────────

@app.route("/categories", methods=["GET","POST"])
@login_required
def categories():
    uid  = session["user_id"]
    conn = get_connection(); cur = conn.cursor()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form.get("name","").strip()
            if name:
                cur.execute("""
                    SELECT COUNT(*) FROM hf_categories
                    WHERE LOWER(name)=LOWER(:1)
                    AND (is_default='Y' OR user_id=:2)
                """, [name, uid])
                if cur.fetchone()[0] > 0:
                    flash("Category already exists.", "warning")
                else:
                    cur.execute(
                        "INSERT INTO hf_categories (name, is_default, user_id) "
                        "VALUES (:1,'N',:2)", [name, uid]
                    )
                    conn.commit()
                    flash(f'Category "{name}" added!', "success")
        elif action == "delete":
            cat_id = request.form.get("cat_id")
            cur.execute(
                "DELETE FROM hf_categories WHERE id=:1 AND is_default='N' AND user_id=:2",
                [cat_id, uid]
            )
            conn.commit()
            flash("Category deleted.", "info")

    cur.execute("""
        SELECT id, name, is_default FROM hf_categories
        WHERE is_default='Y' OR user_id=:1
        ORDER BY is_default DESC, name
    """, [uid])
    all_cats = cur.fetchall()
    cur.close(); conn.close()
    return render_template("categories.html", categories=all_cats)

# ── streaks page ──────────────────────────────────────────────────────────────

@app.route("/streaks")
@login_required
def streaks():
    uid  = session["user_id"]
    conn = get_connection(); cur = conn.cursor()

    cur.execute("""
        SELECT h.name, c.name, s.current_streak, s.longest_streak, s.total_points,
               h.habit_type
        FROM hf_habits h
        LEFT JOIN hf_categories c ON h.category_id=c.id
        LEFT JOIN hf_streaks s    ON h.id=s.habit_id
        WHERE h.user_id=:1 AND h.status='active'
        ORDER BY s.longest_streak DESC NULLS LAST
    """, [uid])
    streak_data = cur.fetchall()

    cur.execute("""
        SELECT NVL(SUM(s.total_points),0)
        FROM hf_streaks s JOIN hf_habits h ON s.habit_id=h.id
        WHERE h.user_id=:1
    """, [uid])
    total_points = cur.fetchone()[0]

    cur.close(); conn.close()
    return render_template("streaks.html",
        streak_data=streak_data, total_points=total_points
    )

# ── profile ───────────────────────────────────────────────────────────────────

@app.route("/profile")
@login_required
def profile():
    uid  = session["user_id"]
    conn = get_connection(); cur = conn.cursor()

    cur.execute(
        "SELECT username, created_at FROM hf_users WHERE id=:1", [uid]
    )
    user = cur.fetchone()

    cur.execute(
        "SELECT COUNT(*) FROM hf_habits WHERE user_id=:1 AND status='active'", [uid]
    )
    active_count = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM hf_habits WHERE user_id=:1", [uid]
    )
    total_count = cur.fetchone()[0]

    cur.execute("""
        SELECT h.name, s.longest_streak
        FROM hf_streaks s JOIN hf_habits h ON s.habit_id=h.id
        WHERE h.user_id=:1
        ORDER BY s.longest_streak DESC FETCH FIRST 1 ROWS ONLY
    """, [uid])
    best = cur.fetchone()

    cur.execute("""
        SELECT NVL(SUM(s.total_points),0)
        FROM hf_streaks s JOIN hf_habits h ON s.habit_id=h.id
        WHERE h.user_id=:1
    """, [uid])
    total_points = cur.fetchone()[0]

    cur.execute("""
        SELECT c.name, COUNT(h.id)
        FROM hf_habits h JOIN hf_categories c ON h.category_id=c.id
        WHERE h.user_id=:1 AND h.status='active'
        GROUP BY c.name ORDER BY COUNT(h.id) DESC
    """, [uid])
    cat_stats = cur.fetchall()

    cur.close(); conn.close()

    return render_template("profile.html",
        username=user[0],
        joined=user[1].strftime("%b %d, %Y") if user[1] else "",
        active_count=active_count,
        total_count=total_count,
        best_habit=best[0] if best else "—",
        best_streak=best[1] if best else 0,
        total_points=total_points,
        cat_stats=cat_stats,
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)