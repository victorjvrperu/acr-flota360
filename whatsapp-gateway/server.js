const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    Browsers
} = require('@whiskeysockets/baileys');
const QRCode = require('qrcode');
const pino = require('pino');
const express = require('express');
const axios = require('axios');
const fs = require('fs');
const path = require('path');

const PORT = parseInt(process.env.PORT || '3334', 10);
const AUTH_DIR = path.join(__dirname, 'auth_info');
const FASTAPI_WEBHOOK_URLS = [
    process.env.FASTAPI_WEBHOOK_URL,
    'http://127.0.0.1:8001/api/v1/heavy/notificaciones/whatsapp-webhook',
    'http://127.0.0.1:8000/api/v1/heavy/notificaciones/whatsapp-webhook'
].filter(Boolean);

let sock = null;
let status = 'disconnected'; // 'disconnected', 'connecting', 'open'
let qrRaw = null;
let qrBase64 = null;
let botNumber = null;
let botName = 'ACR Flota 360° Bot Oficial';
let isConnecting = false;
let reconnectTimeout = null;

function formatWhatsAppJid(to) {
    if (typeof to === 'string') {
        const trimmed = to.trim();
        if (trimmed.endsWith('@lid') || trimmed.endsWith('@s.whatsapp.net') || trimmed.endsWith('@g.us')) {
            return trimmed;
        }
    }
    let clean = to.toString().replace(/[^0-9]/g, '').replace(/^0+/, '');
    if (clean.length === 9 && clean.startsWith('9')) {
        clean = '51' + clean;
    }
    return `${clean}@s.whatsapp.net`;
}

async function forwardToFastAPI(payload) {
    for (const url of FASTAPI_WEBHOOK_URLS) {
        try {
            const resp = await axios.post(url, payload, { timeout: 10000 });
            if (resp.data && resp.data.reply && payload.from) {
                // Si FastAPI devolvió una respuesta automática, responder al usuario
                await sock.sendMessage(payload.from, { text: resp.data.reply });
            }
            return;
        } catch (e) {
            // Siguiente URL si falla
        }
    }
}

async function initBaileys() {
    if (isConnecting) return;
    isConnecting = true;

    if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
    }

    try {
        if (!fs.existsSync(AUTH_DIR)) {
            fs.mkdirSync(AUTH_DIR, { recursive: true });
        }

        const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
        status = 'connecting';

        sock = makeWASocket({
            auth: state,
            logger: pino({ level: 'silent' }),
            printQRInTerminal: true,
            browser: ['ACR Flota 360', 'Chrome', '1.0.0'],
            connectTimeoutMs: 60000,
            defaultQueryTimeoutMs: 60000
        });

        sock.ev.on('creds.update', saveCreds);

        sock.ev.on('connection.update', async (update) => {
            const { connection, lastDisconnect, qr } = update;

            if (qr) {
                qrRaw = qr;
                try {
                    qrBase64 = await QRCode.toDataURL(qr, { margin: 2, scale: 7 });
                } catch (e) {
                    console.error('[Baileys ACR] Error al generar Base64 QR:', e.message);
                }
                console.log('[Baileys ACR] Nuevo código QR generado. Escanee desde la aplicación móvil de WhatsApp.');
            }

            if (connection === 'open') {
                status = 'open';
                qrRaw = null;
                qrBase64 = null;
                isConnecting = false;

                const user = sock.user;
                botNumber = user ? (user.id.split(':')[0] || user.id.split('@')[0]) : null;
                botName = user?.name || 'ACR Flota 360° Bot';

                console.log(`[Baileys ACR] ✅ CONECTADO EXITOSAMENTE con el número: ${botNumber} (${botName})`);

                // Notificar a FastAPI del estado conectado
                forwardToFastAPI({
                    event: 'connected',
                    number: botNumber,
                    name: botName,
                    timestamp: new Date().toISOString()
                }).catch(() => {});
            }

            if (connection === 'close') {
                isConnecting = false;
                status = 'disconnected';
                const statusCode = lastDisconnect?.error?.output?.statusCode;
                const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

                console.warn(`[Baileys ACR] Conexión cerrada. Razón / Status Code: ${statusCode} (Reconectar: ${shouldReconnect})`);

                if (statusCode === DisconnectReason.loggedOut) {
                    console.log('[Baileys ACR] Sesión cerrada voluntariamente. Limpiando credenciales...');
                    try {
                        fs.rmSync(AUTH_DIR, { recursive: true, force: true });
                    } catch (e) {}
                    reconnectTimeout = setTimeout(initBaileys, 2000);
                } else if (shouldReconnect) {
                    reconnectTimeout = setTimeout(initBaileys, 3000);
                }
            }
        });

        // Manejo de mensajes entrantes (consultas de operadores y mecánicos)
        sock.ev.on('messages.upsert', async ({ messages, type }) => {
            if (type !== 'notify') return;
            for (const msg of messages) {
                if (msg.key.fromMe) continue; // Ignorar mensajes enviados por el bot mismo

                const senderJid = msg.key.remoteJid;
                const text = msg.message?.conversation ||
                    msg.message?.extendedTextMessage?.text ||
                    msg.message?.imageMessage?.caption ||
                    '';

                if (!text) continue;

                console.log(`[Baileys ACR] Mensaje recibido de ${senderJid}: "${text}"`);

                forwardToFastAPI({
                    event: 'message_received',
                    from: senderJid,
                    text: text.trim(),
                    pushName: msg.pushName || '',
                    timestamp: msg.messageTimestamp
                }).catch(() => {});
            }
        });

    } catch (err) {
        isConnecting = false;
        status = 'disconnected';
        console.error('[Baileys ACR] Error en initBaileys:', err.message);
        reconnectTimeout = setTimeout(initBaileys, 5000);
    }
}

// ==========================================
// SERVIDOR EXPRESS API REST
// ==========================================
const app = express();
app.use(express.json({ limit: '25mb' }));
app.use(express.urlencoded({ extended: true, limit: '25mb' }));

app.use((req, res, next) => {
    res.header('Access-Control-Allow-Origin', '*');
    res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept');
    next();
});

// 1. Estado del Gateway
app.get('/status', (req, res) => {
    return res.json({
        success: true,
        connected: status === 'open',
        status: status,
        number: botNumber,
        name: botName,
        has_qr: !!qrBase64,
        qr_base64: qrBase64,
        port: PORT
    });
});

// 2. Datos directos del código QR
app.get('/qr-data', (req, res) => {
    return res.json({
        success: true,
        connected: status === 'open',
        status: status,
        number: botNumber,
        has_qr: !!qrBase64,
        qr_base64: qrBase64
    });
});

// 3. Vista HTML interactiva para escanear QR
app.get('/qr', (req, res) => {
    if (status === 'open') {
        return res.send(`
            <!DOCTYPE html>
            <html>
            <head>
                <title>ACR Flota 360° — WhatsApp Conectado</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body { font-family: system-ui, sans-serif; background: #0b0f19; color: #fff; text-align: center; padding: 40px 20px; }
                    .card { max-width: 420px; margin: auto; background: #151d2c; border: 2px solid #10b981; border-radius: 20px; padding: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
                    .badge { display: inline-block; background: #064e3b; color: #34d399; font-weight: 800; padding: 6px 14px; border-radius: 999px; margin-bottom: 15px; font-size: 13px; }
                    h2 { margin: 10px 0; font-size: 20px; }
                    p { color: #94a3b8; font-size: 14px; line-height: 1.5; }
                    .num { font-size: 24px; font-weight: 900; color: #fbbf24; font-family: monospace; margin: 15px 0; }
                </style>
            </head>
            <body>
                <div class="card">
                    <span class="badge">🟢 EN LÍNEA & VINCULADO</span>
                    <h2>ACR Flota 360° WhatsApp Gateway</h2>
                    <div class="num">+${botNumber || ''}</div>
                    <p>El bot emisor de alertas y reportes ejecutivos está conectado 24/7 de forma desatendida.</p>
                </div>
            </body>
            </html>
        `);
    }

    if (!qrBase64) {
        return res.send(`
            <!DOCTYPE html>
            <html>
            <head>
                <title>Iniciando WhatsApp...</title>
                <meta http-equiv="refresh" content="3">
                <style>
                    body { font-family: system-ui, sans-serif; background: #0b0f19; color: #fff; text-align: center; padding: 60px 20px; }
                    .spinner { border: 4px solid #1e293b; border-top: 4px solid #fbbf24; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }
                    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                </style>
            </head>
            <body>
                <div class="spinner"></div>
                <h2>Generando código QR seguro...</h2>
                <p style="color: #64748b;">Espere unos segundos mientras se inicializa el gateway.</p>
            </body>
            </html>
        `);
    }

    return res.send(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>Vincular WhatsApp ACR Flota 360°</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <meta http-equiv="refresh" content="15">
            <style>
                body { font-family: system-ui, sans-serif; background: #0b0f19; color: #fff; text-align: center; padding: 30px 15px; }
                .card { max-width: 440px; margin: auto; background: #151d2c; border: 2px solid #334155; border-radius: 24px; padding: 25px; box-shadow: 0 10px 40px rgba(0,0,0,0.6); }
                img { width: 280px; height: 280px; border-radius: 16px; background: #fff; padding: 10px; margin: 15px auto; display: block; }
                h2 { margin: 5px 0; font-size: 19px; }
                p { color: #94a3b8; font-size: 13px; line-height: 1.5; margin: 8px 0; }
                .steps { text-align: left; background: #0b0f19; border-radius: 14px; padding: 14px 18px; margin-top: 15px; font-size: 12px; color: #cbd5e1; }
                .steps ol { margin: 0; padding-left: 20px; }
                .steps li { margin: 6px 0; }
            </style>
        </head>
        <body>
            <div class="card">
                <h2>📲 Vincular Número Emisor WhatsApp</h2>
                <p>Escanee este código con el WhatsApp oficial de la empresa (ACR Flota 360°).</p>
                <img src="${qrBase64}" alt="Código QR WhatsApp" />
                <div class="steps">
                    <strong>Pasos en el teléfono:</strong>
                    <ol>
                        <li>Abra WhatsApp en el celular designado.</li>
                        <li>Toque <b>Dispositivos vinculados</b> > <b>Vincular un dispositivo</b>.</li>
                        <li>Apunte la cámara a esta pantalla para completar el enlace.</li>
                    </ol>
                </div>
            </div>
        </body>
        </html>
    `);
});

// 4. Enviar Mensaje de Texto
app.post('/send-message', async (req, res) => {
    try {
        const { to, message } = req.body;

        if (!to || !message) {
            return res.status(400).json({ success: false, error: 'Parámetros to y message requeridos' });
        }

        if (status !== 'open' || !sock) {
            return res.status(503).json({
                success: false,
                error: `El bot de WhatsApp no está conectado actualmente (Estado: ${status}).`
            });
        }

        const jid = formatWhatsAppJid(to);
        console.log(`[Baileys ACR] Enviando mensaje a ${jid}: "${message.substring(0, 50)}..."`);

        try {
            await sock.sendPresenceUpdate('composing', jid);
            const delay = Math.min(Math.max(message.length * 10, 800), 2200);
            await new Promise(r => setTimeout(r, delay));
        } catch (e) {}

        const sent = await sock.sendMessage(jid, { text: message });

        try {
            await sock.sendPresenceUpdate('paused', jid);
        } catch (e) {}

        return res.json({
            success: true,
            id: sent?.key?.id || ('wamid_' + Date.now()),
            message: 'Mensaje despachado exitosamente por WhatsApp'
        });
    } catch (err) {
        console.error('[Baileys ACR] Error al enviar mensaje:', err.message);
        return res.status(500).json({ success: false, error: err.message });
    }
});

// 5. Enviar Documento PDF (Reportes de Flota / OTs)
app.post('/send-document', async (req, res) => {
    try {
        const { to, documentUrl, fileName, caption } = req.body;

        if (!to || !documentUrl) {
            return res.status(400).json({ success: false, error: 'Parámetros to y documentUrl requeridos' });
        }

        if (status !== 'open' || !sock) {
            return res.status(503).json({ success: false, error: 'WhatsApp no está conectado' });
        }

        const jid = formatWhatsAppJid(to);
        let docBuffer = null;

        if (documentUrl.startsWith('http://') || documentUrl.startsWith('https://')) {
            const resp = await axios.get(documentUrl, { responseType: 'arraybuffer', timeout: 30000 });
            docBuffer = Buffer.from(resp.data);
        } else if (fs.existsSync(documentUrl)) {
            docBuffer = fs.readFileSync(documentUrl);
        } else {
            return res.status(400).json({ success: false, error: 'No se encontró el archivo del documento especificado' });
        }

        console.log(`[Baileys ACR] Enviando PDF "${fileName || 'reporte.pdf'}" a ${jid}`);

        try {
            await sock.sendPresenceUpdate('composing', jid);
            await new Promise(r => setTimeout(r, 1200));
        } catch (e) {}

        const sent = await sock.sendMessage(jid, {
            document: docBuffer,
            mimetype: 'application/pdf',
            fileName: fileName || 'reporte.pdf',
            caption: caption || ''
        });

        try {
            await sock.sendPresenceUpdate('paused', jid);
        } catch (e) {}

        return res.json({
            success: true,
            id: sent?.key?.id || ('wamid_' + Date.now()),
            message: 'Documento PDF enviado exitosamente'
        });
    } catch (err) {
        console.error('[Baileys ACR] Error al enviar PDF:', err.message);
        return res.status(500).json({ success: false, error: err.message });
    }
});

// 6. Cerrar Sesión / Forzar Nuevo QR
app.post(['/logout', '/reset'], async (req, res) => {
    try {
        if (sock) {
            try { await sock.logout(); } catch (e) {}
            try {
                sock.ev.removeAllListeners();
                sock.end(undefined);
            } catch (e) {}
            sock = null;
        }

        status = 'disconnected';
        botNumber = null;
        botName = null;
        qrRaw = null;
        qrBase64 = null;
        isConnecting = false;

        try {
            fs.rmSync(AUTH_DIR, { recursive: true, force: true });
        } catch (e) {}

        setTimeout(initBaileys, 1000);

        return res.json({
            success: true,
            message: 'Sesión de WhatsApp cerrada. Se está generando un nuevo código QR.'
        });
    } catch (err) {
        return res.status(500).json({ success: false, error: err.message });
    }
});

// Iniciar servidor y socket Baileys
app.listen(PORT, '0.0.0.0', () => {
    console.log(`[ACR WhatsApp Gateway] Servidor HTTP escuchando en http://127.0.0.1:${PORT}`);
    initBaileys();
});
