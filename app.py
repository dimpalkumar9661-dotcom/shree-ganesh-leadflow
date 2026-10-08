"""LeadFlow: minimal stdlib lead-capture backend. Python 3.10+."""
import os, json, sqlite3, secrets, smtplib, ssl, logging
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from threading import Lock

BASE=Path(__file__).resolve().parent
DB=Path(os.environ.get('LEADFLOW_DB',str(BASE/'leads.sqlite3')))
HOST=os.environ.get('HOST','127.0.0.1')
PORT=int(os.environ.get('PORT','8000'))
TOKEN=os.environ.get('ADMIN_TOKEN','')
LOCK=Lock()
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')

def init():
    with sqlite3.connect(DB) as c:
        c.execute('CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT, company TEXT, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT "new", consent INTEGER NOT NULL)')

def notify(d):
    if not all(os.environ.get(x) for x in ('SMTP_HOST','SMTP_USER','SMTP_PASSWORD','NOTIFY_TO')): return
    m=EmailMessage();m['Subject']='New LeadFlow inquiry';m['From']=os.environ['SMTP_USER'];m['To']=os.environ['NOTIFY_TO']
    m.set_content('New inquiry:\n'+ '\n'.join(f'{k}: {v}' for k,v in d.items() if k!='consent'))
    with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.environ.get('SMTP_PORT','587')),timeout=12) as s:
        s.starttls(context=ssl.create_default_context());s.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD']);s.send_message(m)

class Handler(BaseHTTPRequestHandler):
    def respond(self,status,data):
        payload=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(payload)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/':
            content=(BASE/'index.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(content)));self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(content);return
        if path in ('/dashboard', '/dashboard/', '/dashboard.html'):
            dashboard=BASE/'dashboard.html'
            if not dashboard.is_file():return self.respond(503,{'error':'dashboard.html is missing. Copy it beside app.py and restart the server.'})
            content=dashboard.read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-store');self.send_header('X-Frame-Options','DENY');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(content);return
        if path=='/health': return self.respond(200,{'ok':True})
        if path=='/api/leads':
            if not TOKEN or not secrets.compare_digest(self.headers.get('X-Admin-Token',''),TOKEN): return self.respond(403,{'error':'Forbidden'})
            with sqlite3.connect(DB) as c:
                c.row_factory=sqlite3.Row;rows=[dict(r) for r in c.execute('SELECT * FROM leads ORDER BY id DESC LIMIT 500')]
            return self.respond(200,{'leads':rows})
        return self.respond(404,{'error':'Not found'})
    def do_PATCH(self):
        path=urlparse(self.path).path
        parts=path.strip('/').split('/')
        if len(parts)!=4 or parts[:2]!=['api','leads'] or parts[3]!='status' or not parts[2].isdigit():return self.respond(404,{'error':'Not found'})
        if not TOKEN or not secrets.compare_digest(self.headers.get('X-Admin-Token',''),TOKEN):return self.respond(403,{'error':'Forbidden'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=256:raise ValueError()
            payload=json.loads(self.rfile.read(length))
            status=payload.get('status')
            if status not in ('new','contacted','converted','lost'):raise ValueError()
        except (ValueError,TypeError,AttributeError,json.JSONDecodeError):return self.respond(400,{'error':'Invalid status'})
        with LOCK:
            with sqlite3.connect(DB) as c:
                updated=c.execute('UPDATE leads SET status=? WHERE id=?',(status,int(parts[2]))).rowcount
        return self.respond(200,{'ok':True}) if updated else self.respond(404,{'error':'Lead not found'})
    def do_POST(self):
        if urlparse(self.path).path!='/api/leads':return self.respond(404,{'error':'Not found'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=8192:return self.respond(413,{'error':'Invalid request size'})
            d=json.loads(self.rfile.read(length));
            if not isinstance(d,dict):raise ValueError()
            for key,limit in [('name',100),('email',254),('phone',30),('company',120),('message',1500)]:
                v=d.get(key,'')
                if not isinstance(v,str) or len(v)>limit:raise ValueError()
                d[key]=v.strip()
            if not d['name'] or not d['message'] or '@' not in d['email'] or d.get('consent') is not True:raise ValueError()
        except (ValueError,TypeError,json.JSONDecodeError):return self.respond(400,{'error':'Please provide valid fields and consent'})
        with LOCK:
            with sqlite3.connect(DB) as c:
                cur=c.execute('INSERT INTO leads (created_at,name,email,phone,company,message,consent) VALUES (?,?,?,?,?,?,1)',(datetime.now(timezone.utc).isoformat(),d['name'],d['email'],d['phone'],d['company'],d['message']))
                lead_id=cur.lastrowid
        try:notify(d)
        except Exception:logging.exception('Email notification failed; lead was saved')
        return self.respond(201,{'ok':True,'id':lead_id})

if __name__=='__main__':
    server=ThreadingHTTPServer((HOST,PORT),Handler)
    init()
    print(f'Shree Ganesh AI Solutions running at http://{HOST}:{PORT}',flush=True)
    print(f'Dashboard: http://{HOST}:{PORT}/dashboard',flush=True)
    print(f'Application folder: {BASE}',flush=True)
    print(f'Lead database: {DB.resolve()}',flush=True)
    server.serve_forever()
