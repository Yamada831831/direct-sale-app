from flask import Flask, request, jsonify, render_template
from datetime import datetime
import csv
import os
from flask import request
import math
from collections import defaultdict
from datetime import timedelta
from flask import session  # 必要に応じて


app = Flask(__name__)
app.secret_key = 'ohashi'

# 保存先
DATA_DIR = 'data'
SALES_FILE = os.path.join(DATA_DIR, 'sales.csv')
FIELDNAMES = ['datetime', 'product_name', 'standard_name', 'price_amount', 'quantity', 'recovered_qty']

# フォルダとファイルを初期化
os.makedirs(DATA_DIR, exist_ok=True)

if not os.path.exists(SALES_FILE):
    with open(SALES_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

# CSV初期化関数（なければ作成）
def ensure_csv_file(path, fieldnames):
    if not os.path.exists(path):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

# 初期化実行
ensure_csv_file('data/standards.csv', ['name', 'usage_ratio'])
ensure_csv_file('data/costs.csv', ['product_name', 'week_start', 'cost_per_unit'])


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/recover')
def recover():
    return render_template('recover.html')

@app.route('/summary')
def summary():
    return render_template('summary.html')

@app.route('/api/sales/today', methods=['GET'])
def get_today_sales():
    today = datetime.now().strftime('%Y-%m-%d')
    result = []

    with open(SALES_FILE, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['datetime'].startswith(today):
                result.append(row)

    return jsonify(result)

@app.route('/api/sales/summary', methods=['GET'])
def summary_sales():
    query_date = request.args.get('date')
    if not query_date:
        return jsonify({'error': 'dateパラメータが必要です'}), 400

    # 月曜起点の週開始日を出品日に合わせて算出
    def get_week_start(date_str):
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        start = dt - timedelta(days=dt.weekday())
        return start.strftime('%Y-%m-%d')

    summary_list = []

    # 各CSV読み込み
    with open(SALES_FILE, 'r', encoding='utf-8') as f:
        sales_data = [row for row in csv.DictReader(f) if row['datetime'].startswith(query_date)]

    with open('data/standards.csv', 'r', encoding='utf-8-sig') as f:
        usage_map = {row['name']: float(row['usage_ratio']) for row in csv.DictReader(f)}

    with open('data/costs.csv', 'r', encoding='utf-8-sig') as f:
        cost_rows = list(csv.DictReader(f))

    # 集計
    for row in sales_data:
        product = row['product_name']
        standard = row['standard_name']
        price = int(row['price_amount'])
        quantity = int(row['quantity'])
        recovered = int(row['recovered_qty']) if row['recovered_qty'] else 0
        sold = quantity - recovered
        revenue = sold * price

        usage = usage_map.get(standard, 1.0)

        # 原価取得（出品日の週）
        week_start = get_week_start(query_date)
        cost_row = next((r for r in cost_rows if r['product_name'] == product and r['week_start'] == week_start), None)
        cost_per_unit = float(cost_row['cost_per_unit']) if cost_row else 0.0
        cost = round(sold * usage * cost_per_unit, 2)

        profit = revenue - cost
        cost_rate = round(cost / revenue, 2) if revenue else 0.0

        summary_list.append({
            'product_name': product,
            'standard_name': standard,
            'price': price,
            'quantity': quantity,
            'recovered': recovered,
            'sold': sold,
            'revenue': revenue,
            'unit_cost': cost_per_unit,
            'usage': usage,
            'cost': cost,
            'cost_rate': cost_rate,
            'profit': profit
        })

# 最後に結果をセッションに保存
    session['summary_result'] = summary_list
    session['total_revenue'] = sum(row['revenue'] for row in summary_list)
    session['total_cost'] = sum(row['cost'] for row in summary_list)
    session['total_profit'] = sum(row['profit'] for row in summary_list)

    return jsonify(summary_list)

@app.route('/export/summary_csv')
def export_summary_csv():
    import io
    from flask import Response
    from datetime import datetime

    summary_rows = session.get('summary_result', [])
    if not summary_rows:
        return "集計データがありません", 400

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['商品', '規格', '金額', '出品数', '回収数', '販売数', '売上', '原価', '原価率', '利益'])

    for row in summary_rows:
        writer.writerow([
            row.get('product_name', ''),
            row.get('standard_name', ''),
            f"¥{row.get('price', 0)}",
            row.get('quantity', 0),
            row.get('recovered', 0),
            row.get('sold', 0),
            f"¥{row.get('revenue', 0)}",
            f"¥{row.get('cost', 0)}",
            f"{row.get('cost_rate', 0)}%",
            f"¥{row.get('profit', 0)}"
        ])

    writer.writerow([
        '合計', '', '', '', '', '',
        f"¥{session.get('total_revenue', 0)}",
        f"¥{session.get('total_cost', 0)}",
        '',
        f"¥{session.get('total_profit', 0)}"
    ])

    # ← utf-8-sig でエンコードして出力！
    encoded_output = output.getvalue().encode('utf-8-sig')
    output.close()

    filename = f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        encoded_output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )



@app.route('/api/sales/summary_range', methods=['GET'])
def summary_sales_range():
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    if not from_date or not to_date:
        return jsonify({'error': 'fromとtoパラメータが必要です'}), 400

    def get_week_start(date_str):
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        start = dt - timedelta(days=dt.weekday())
        return start.strftime('%Y-%m-%d')

    # データ読み込み
    with open(SALES_FILE, 'r', encoding='utf-8') as f:
        sales_data = [
            row for row in csv.DictReader(f)
            if from_date <= row['datetime'][:10] <= to_date
        ]

    with open('data/standards.csv', 'r', encoding='utf-8-sig') as f:
        usage_map = {row['name']: float(row['usage_ratio']) for row in csv.DictReader(f)}

    with open('data/costs.csv', 'r', encoding='utf-8-sig') as f:
        cost_rows = list(csv.DictReader(f))

    # 集計用辞書
    summary_dict = defaultdict(lambda: {
        'product_name': '',
        'standard_name': '',
        'price': 0,
        'quantity': 0,
        'recovered': 0,
        'sold': 0,
        'revenue': 0,
        'cost': 0.0,
        'profit': 0.0
    })

    for row in sales_data:
        date = row['datetime'][:10]
        product = row['product_name']
        standard = row['standard_name']
        price = int(row['price_amount'])
        quantity = int(row['quantity'])
        recovered = int(row['recovered_qty']) if row['recovered_qty'] else 0
        sold = quantity - recovered
        usage = usage_map.get(standard, 1.0)

        # 原価計算（週単位）
        week_start = get_week_start(date)
        cost_row = next((r for r in cost_rows if r['product_name'] == product and r['week_start'] == week_start), None)
        cost_per_unit = float(cost_row['cost_per_unit']) if cost_row else 0.0
        cost = round(sold * usage * cost_per_unit, 2)

        key = f"{product}|{standard}|{price}"
        entry = summary_dict[key]
        entry['product_name'] = product
        entry['standard_name'] = standard
        entry['price'] = price
        entry['quantity'] += quantity
        entry['recovered'] += recovered
        entry['sold'] += sold
        entry['revenue'] += sold * price
        entry['cost'] += cost
        entry['profit'] += (sold * price) - cost

    # 最終整形
    result = []
    for row in summary_dict.values():
        revenue = row['revenue']
        row['cost'] = round(row['cost'], 2)
        row['profit'] = round(row['profit'], 2)
        row['cost_rate'] = round(row['cost'] / revenue, 2) if revenue else 0.0
        result.append(row)

    return jsonify(result)

@app.route('/api/suggest/product')
def suggest_product():
    seen = set()
    suggestions = []
    with open(SALES_FILE, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            name = row['product_name']
            if name not in seen:
                seen.add(name)
                suggestions.append(name)
    return jsonify(suggestions)

@app.route('/api/suggest/standard')
def suggest_standard():
    with open('data/standards.csv', 'r', encoding='utf-8-sig') as f:
        standards = [row['name'] for row in csv.DictReader(f)]
    return jsonify(standards)

@app.route('/api/suggest/price')
def suggest_price():
    seen = set()
    suggestions = []
    with open(SALES_FILE, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            price = row['price_amount']
            if price not in seen:
                seen.add(price)
                suggestions.append(price)
    return jsonify(suggestions)

@app.route('/master')
def master():
    return render_template('master.html')


@app.route('/api/master/standards', methods=['GET', 'POST', 'DELETE'])
def manage_standards():
    path = 'data/standards.csv'
    fieldnames = ['name', 'usage_ratio']

    if request.method == 'GET':
        with open(path, 'r', encoding='utf-8-sig') as f:
            return jsonify(list(csv.DictReader(f)))

    if request.method == 'POST':
        data = request.json
        new_row = {'name': data['name'], 'usage_ratio': data['usage_ratio']}

        # 重複チェックしてなければ追加
        rows = []
        exists = False
        with open(path, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                if row['name'] == data['name']:
                    exists = True
                rows.append(row)

        if not exists:
            rows.append(new_row)
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        return jsonify({'status': 'ok'})

    if request.method == 'DELETE':
        name = request.args.get('name')
        rows = []
        with open(path, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                if row['name'] != name:
                    rows.append(row)

        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        return jsonify({'status': 'deleted'})


@app.route('/api/master/costs', methods=['GET', 'POST', 'DELETE'])
def manage_costs():
    path = 'data/costs.csv'
    fieldnames = ['product_name', 'week_start', 'cost_per_unit']

    if request.method == 'GET':
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                data = list(csv.DictReader(f))
                print('読み込んだ原価マスタ：', data)
                return jsonify(data)
        except Exception as e:
            print('読み込みエラー：', e)
            return jsonify({'error': '読み込み失敗', 'detail': str(e)}), 500

    # POST, DELETE の処理はここに続けて書く（略）


    if request.method == 'POST':
        data = request.json
        new_row = {
            'product_name': data['product_name'],
            'week_start': data['week_start'],
            'cost_per_unit': data['cost_per_unit']
        }

        rows = []
        updated = False
        with open(path, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                if row['product_name'] == data['product_name'] and row['week_start'] == data['week_start']:
                    row['cost_per_unit'] = data['cost_per_unit']
                    updated = True
                rows.append(row)

        if not updated:
            rows.append(new_row)

        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        return jsonify({'status': 'ok'})

    if request.method == 'DELETE':
        product = request.args.get('product_name')
        week = request.args.get('week_start')
        rows = []
        with open(path, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                if not (row['product_name'] == product and row['week_start'] == week):
                    rows.append(row)

        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        return jsonify({'status': 'deleted'})


@app.route('/api/sales/recover', methods=['POST'])
def update_recovery():
    data = request.json  # [{'datetime': '2025-04-10 10:00', 'recovered_qty': 3}, ...]

    updated_rows = []
    with open(SALES_FILE, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            for item in data:
                if row['datetime'] == item['datetime']:
                    row['recovered_qty'] = str(item['recovered_qty'])
            updated_rows.append(row)

    with open(SALES_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(updated_rows)

    return jsonify({'status': 'ok', 'message': '回収数を保存しました'}), 200


@app.route('/api/sales/add_or_update', methods=['POST'])
def add_or_update_sale():
    data = request.json
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M')
    today_str = now.strftime('%Y-%m-%d')

    # リクエストからデータ取得
    product = data.get('product_name')
    standard = data.get('standard_name')
    price = int(data.get('price_amount'))
    quantity = int(data.get('quantity'))

    updated = False
    rows = []

    # 既存データ読み込み
    with open(SALES_FILE, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 同じ日＋商品＋規格＋金額なら加算
            if (
                row['datetime'][:10] == today_str and
                row['product_name'] == product and
                row['standard_name'] == standard and
                int(row['price_amount']) == price
            ):
                row['quantity'] = str(int(row['quantity']) + quantity)
                updated = True
            rows.append(row)

    # 新規追加
    if not updated:
        rows.append({
            'datetime': now_str,
            'product_name': product,
            'standard_name': standard,
            'price_amount': str(price),
            'quantity': str(quantity),
            'recovered_qty': ''
        })

    # 書き込み
    with open(SALES_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    return jsonify({'status': 'ok', 'message': '登録完了！'}), 200


if __name__ == '__main__':
    app.run(debug=True)
