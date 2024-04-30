from flask import Flask, request, session, flash, redirect, url_for, render_template
from app.models import Transaction, User, db
from .debt_resolver import Solution, read_db_to_adjacency_matrix
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func
from datetime import datetime
from .forms import SendMoneyForm
from sqlalchemy.orm import aliased
from .models import Group, GroupTransaction

def init_debt_routes(app):
    @app.route("/user_profile")
    def user_profile(title='Profile page'):
        if 'user_id' not in session:
            flash('Please log in to view your profile.', 'warning')
            return redirect(url_for('login'))
            # Here you can add more logic to handle user profile data
        return render_template('user_profile.html', title='Profile page')

    @app.route('/settle_debts')
    def settle_debts_view():
        if 'user_id' not in session:
            flash('Please log in to proceed.', 'warning')
            return redirect(url_for('login'))

        # Placeholder for settlement algorithm
        transactions = []  # Simulate transactions
        return render_template('result.html', transactions=transactions)

    @app.route('/dashboard')
    def dashboard():
        if 'user_id' not in session:
            flash('Please log in to view the dashboard.', 'warning')
            return redirect(url_for('login'))
        
        # Subquery for total credits per user
        credit_subquery = db.session.query(
            Transaction.payer_id.label('user_id'),
            func.sum(func.abs(Transaction.amount)).label('total_credit')  # Using abs() to ensure positive values
        ).group_by(Transaction.payer_id).subquery()

        # Subquery for total debts per user
        debt_subquery = db.session.query(
            Transaction.debtor_id.label('user_id'),
            func.sum(func.abs(Transaction.amount)).label('total_debt')  # Using abs() to ensure positive values
        ).group_by(Transaction.debtor_id).subquery()

        # Main query to calculate net balances, total credits, and total debts
        net_balances = db.session.query(
            User.first_name, User.last_name,
            func.coalesce(credit_subquery.c.total_credit, 0).label('total_incomings'),
            func.coalesce(debt_subquery.c.total_debt, 0).label('total_outgoings'),
            (func.coalesce(credit_subquery.c.total_credit, 0) - func.coalesce(debt_subquery.c.total_debt, 0)).label('net_balance')
        ).outerjoin(credit_subquery, User.id == credit_subquery.c.user_id) \
        .outerjoin(debt_subquery, User.id == debt_subquery.c.user_id) \
        .group_by(User.first_name, User.last_name) \
        .all()

        # Define aliases for User model
        Payer = aliased(User, name='payer')
        Debtor = aliased(User, name='debtor')


        # SEPARATE TABLE BELOW: Fetch all transactions with payer and debtor details
        transactions = db.session.query(
            Transaction.item_name,
            Payer.first_name.label('payer_first_name'),
            Payer.last_name.label('payer_last_name'),
            Debtor.first_name.label('debtor_first_name'),
            Debtor.last_name.label('debtor_last_name'),
            Transaction.amount,
            Transaction.time_date
        ).join(Payer, Payer.id == Transaction.payer_id) \
        .join(Debtor, Debtor.id == Transaction.debtor_id).all() # THIS IS WHERE ITEM NAME IS DROPPED, I TRIED TO GET IT TO WORK BUT COULDN'T

        return render_template('dashboard.html', net_balances=net_balances, transactions=transactions)


    @app.route('/update_monetary_value', methods=['GET', 'POST'])
    def update_monetary_value():
        if request.method == 'POST':
            # Print the form data
            print("Form Data:", request.form)

            item_id = request.form.get('user_id')
            amount = float(request.form.get('amount'))

            debt_item = Transaction.query.get_or_404(item_id)
            debt_item.monetary_value += amount
            db.session.commit()
            print("successful")
            return redirect(url_for('home'))

        # If it's a GET request, render the form
        items = Transaction.query.all()
        return render_template('update_money.html', items=items)

    # Route to retrieve and display monetary values for the logged-in user
    @app.route('/show_monetary_values')
    def show_monetary_values():
        # Check if user is logged in
        user_id = session.get('user_id')
        if not user_id:
            flash('Please log in to view monetary values.', 'warning')
            return redirect(url_for('login'))

        try:
            # Query the database for transactions where the user is the payer
            credit_transactions = Transaction.query.filter_by(payer_id=user_id).all()
            total_credit = sum(transaction.amount for transaction in credit_transactions)

            # Query the database for transactions where the user is the debtor
            debit_transactions = Transaction.query.filter_by(debtor_id=user_id).all()
            total_debit = sum(transaction.amount for transaction in debit_transactions)

            # Calculate net balance
            net_balance = total_credit - total_debit

            # Prepare data for template
            monetary_values = [
                {'description': 'Total Credit', 'value': total_credit},
                {'description': 'Total Debit', 'value': -total_debit},  # Debit shown as positive number
                {'description': 'Net Balance', 'value': net_balance}
            ]

            return render_template(
                'show_balance.html',
                monetary_values=monetary_values,
                total_monetary_value=net_balance  # Or whatever summary statistic you prefer
            )
        except Exception as e:
            # In a production app, you'd want to log this error.
            flash('An error occurred while fetching monetary values.', 'danger')
            return redirect(url_for('user_profile'))

    # Route to display the list of users and send money


    @app.route('/input_debts', methods=['GET', 'POST'])
    def input_debts():
        if request.method == 'POST':
            if 'user_id' not in session:
                flash('Please log in to input debts.', 'warning')
                return redirect(url_for('login'))

            item_name = request.form['item_name']
            user_id = session['user_id']
            debtor_id = int(request.form.get('debtor'))
            amount = float(request.form.get('amount'))

            payer = User.query.get_or_404(user_id)
            debtor = User.query.get_or_404(debtor_id)

            try:
                debt_item = Transaction(
                    item_name=item_name,
                    amount=-amount, 
                    payer_id=payer.id, 
                    debtor_id=debtor.id)
                
                db.session.add(debt_item)
                db.session.commit()
                flash('Debt recorded successfully.', 'success')
            except SQLAlchemyError as e:
                db.session.rollback()
                flash(str(e), 'danger')

            return redirect(url_for('input_debts'))

        users = User.query.all()
        return render_template('input_debts.html', users=users)

    @app.route('/settle_up', methods=['GET', 'POST'])
    def settle_up():
        if request.method == 'POST':
            if 'user_id' not in session:
                flash('Please log in to Settle Up Functions', 'warning')
                return redirect(url_for('login'))

            try:
                adjacency_matrix, persons = read_db_to_adjacency_matrix()
                solver = Solution()
                payment_instructions = solver.minCashFlow(adjacency_matrix, persons)
                return render_template('result2.html', payments=payment_instructions)
            except NotFound:
                flash('No transactions found to settle up.', 'warning')
            except Exception as e:
                flash(str(e), 'danger')

        return render_template('settle_up.html')

    def has_sufficient_funds(user_id, amount):
        total_credit = db.session.query(db.func.sum(Transaction.amount)).filter(Transaction.debtor_id == user_id).scalar() or 0
        total_debit = db.session.query(db.func.sum(Transaction.amount)).filter(Transaction.payer_id == user_id).scalar() or 0
        return (total_credit + total_debit) >= amount

    @app.route('/create_group', methods=['GET', 'POST'])
    def create_group():
        if request.method == 'POST':
            group_name = request.form.get('group_name')
            if group_name:
                group = Group(name=group_name)
                db.session.add(group)
                db.session.commit()
                flash('Group created successfully', 'success')
                return redirect(url_for('list_groups'))
        return render_template('create_group.html')

    @app.route('/list_groups')
    def list_groups():
        groups = Group.query.all()
        return render_template('list_groups.html', groups=groups)

    @app.route('/add_transaction_to_group', methods=['GET', 'POST'])
    def add_transaction_to_group():
        if request.method == 'POST':
            group_id = request.form.get('group_id', type=int)
            payer_id = session.get('user_id')  # Assuming the payer is the logged-in user
            amount = request.form.get('amount', type=float)
            description = request.form.get('description', type=str)

            transaction = GroupTransaction(group_id=group_id, payer_id=payer_id, amount=amount, description=description)
            db.session.add(transaction)
            db.session.commit()
            flash('Transaction added successfully', 'success')
            return redirect(url_for('view_group', group_id=group_id))
        groups = Group.query.all()
        return render_template('add_transaction_to_group.html', groups=groups)

    @app.route('/group/<int:group_id>')
    def view_group(group_id):
        group = Group.query.get_or_404(group_id)
        transactions = GroupTransaction.query.filter_by(group_id=group_id).all()
        return render_template('view_group.html', group=group, transactions=transactions)

    @app.route('/dashboard_personal')
    def dashboard_personal():
        user_id = session.get('user_id')
        if not user_id:
            flash('Please log in', 'warning')
            return redirect(url_for('login'))

        try:
            # Fetch credit and debit transactions
            credit_transactions = Transaction.query.filter_by(payer_id=user_id).all()
            debit_transactions = Transaction.query.filter_by(debtor_id=user_id).all()

            # Sum up credits and debits
            total_credit = sum(transaction.amount for transaction in credit_transactions)
            total_debit = sum(transaction.amount for transaction in debit_transactions)

            # Calculate net balance
            net_balance = total_credit - total_debit

            # Prepare data for template
            monetary_values = {
                'credits': credit_transactions,
                'debts': debit_transactions,
                'total_credit': total_credit,
                'total_debit': total_debit,
                'net_balance': net_balance
            }

            # Combine credit and debit transactions for the transaction history table
            transactions = credit_transactions + debit_transactions
            transactions.sort(key=lambda x: x.time_date, reverse=True)

            return render_template('dashboard_personal.html', monetary_values=monetary_values, transactions=transactions)

        except Exception as e:
            flash('Error retrieving your data', 'error')
            return redirect(url_for('login'))
