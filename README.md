# Simple POS (Python / Flask)

Minimal, modern point-of-sale web app. Python + Flask + SQLite — no other setup needed.

## Run
```
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 (other PCs on the network: http://<this-pc-ip>:5000)

Default logins (change them on first login via "Password"):
- Admin: `admin` / `admin123`
- Cashier: `cashier` / `cashier123`

## Roles
| Feature | Admin | Cashier |
|---|---|---|
| New sale (POS screen, barcode scan, cash/card/QR, discount, change) | ✓ | ✓ |
| Print receipt | ✓ | ✓ |
| Sales history | All users | Own sales only |
| Dashboard (today/month sales, profit, 7-day chart, top items, low stock) | ✓ | – |
| Products (add/edit/disable, cost & price, stock, low-stock alert) | ✓ | – |
| Categories | ✓ | – |
| Users (add cashiers/admins, reset passwords, disable) | ✓ | – |
| Void a sale (returns stock) | ✓ | – |

## Settings (environment variables)
- `POS_SHOP_NAME` – shown on header & receipts (default "My Shop")
- `POS_CURRENCY` – default "Rs."
- `POS_TAX_RATE` – e.g. `0.18` for 18% (default 0 = no tax line)
- `POS_SECRET_KEY` – set a long random value in production

Data is stored in `pos.db` next to `app.py`. Delete it to start fresh (sample products are added on first run).

## Production
`debug=True` is for development. For real use:
```
pip install waitress
waitress-serve --port=5000 app:app
```
