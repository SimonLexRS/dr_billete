/**
 * Dr. Billetes - Frontend Application
 * Detector de Billetes Ilegales BCB Bolivia
 */

document.addEventListener('DOMContentLoaded', () => {
    // ===================== State =====================
    let currentImage = null;
    let selectedDenom = null;
    let cameraStream = null;

    // ===================== DOM Elements =====================
    const tabs = document.querySelectorAll('.tab');
    const tabContents = document.querySelectorAll('.tab-content');

    const cameraVideo = document.getElementById('cameraVideo');
    const cameraCanvas = document.getElementById('cameraCanvas');
    const cameraOverlay = document.getElementById('cameraOverlay');
    const cameraContainer = document.getElementById('cameraContainer');
    const btnStartCamera = document.getElementById('btnStartCamera');
    const btnCapture = document.getElementById('btnCapture');

    const uploadZone = document.getElementById('uploadZone');
    const fileInput = document.getElementById('fileInput');
    const imagePreview = document.getElementById('imagePreview');
    const previewImg = document.getElementById('previewImg');
    const btnRemoveImage = document.getElementById('btnRemoveImage');
    const btnScan = document.getElementById('btnScan');
    const resultsPanel = document.getElementById('resultsPanel');

    const denomBtns = document.querySelectorAll('.denom-btn');
    const serialInput = document.getElementById('serialInput');
    const btnVerify = document.getElementById('btnVerify');
    const manualResultsPanel = document.getElementById('manualResultsPanel');

    const btnTrain = document.getElementById('btnTrain');
    const trainingProgress = document.getElementById('trainingProgress');
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');

    const loadingOverlay = document.getElementById('loadingOverlay');
    const loadingText = document.getElementById('loadingText');

    // ===================== Tabs =====================
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.tab;
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(tc => tc.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(`tab-${target}`).classList.add('active');

            if (target === 'database') loadDatabaseView();
            if (target === 'training') loadModelInfo();
        });
    });

    // ===================== Camera =====================
    cameraOverlay.addEventListener('click', startCamera);
    btnStartCamera.addEventListener('click', startCamera);

    async function startCamera() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            const isLocalhost = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
            if (!isLocalhost) {
                alert(
                    'La camara requiere un contexto seguro (HTTPS).\n\n' +
                    'Acceda desde http://localhost:5000 en lugar de usar la IP,\n' +
                    'o suba una imagen del billete usando el boton de carga.'
                );
            } else {
                alert('Su navegador no soporta acceso a la camara.\nUse la opcion de subir imagen.');
            }
            return;
        }
        try {
            cameraStream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
            });
            cameraVideo.srcObject = cameraStream;
            cameraOverlay.classList.add('hidden');
            cameraContainer.querySelector('.camera-frame').classList.add('active');
            cameraContainer.style.borderStyle = 'solid';
            btnCapture.disabled = false;
            btnStartCamera.textContent = 'Camara Activa';
            btnStartCamera.disabled = true;
        } catch (err) {
            alert('No se pudo acceder a la camara: ' + err.message + '\n\nUse la opcion de subir imagen.');
        }
    }

    btnCapture.addEventListener('click', () => {
        if (!cameraStream) return;
        cameraCanvas.width = cameraVideo.videoWidth;
        cameraCanvas.height = cameraVideo.videoHeight;
        const ctx = cameraCanvas.getContext('2d');
        ctx.drawImage(cameraVideo, 0, 0);
        const dataUrl = cameraCanvas.toDataURL('image/jpeg', 0.9);
        setImage(dataUrl);
        stopCamera();
    });

    function stopCamera() {
        if (cameraStream) {
            cameraStream.getTracks().forEach(t => t.stop());
            cameraStream = null;
        }
        cameraOverlay.classList.remove('hidden');
        cameraContainer.querySelector('.camera-frame').classList.remove('active');
        cameraContainer.style.borderStyle = 'dashed';
        btnCapture.disabled = true;
        btnStartCamera.disabled = false;
        btnStartCamera.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg> Activar Camara`;
    }

    // ===================== Upload =====================
    uploadZone.addEventListener('click', () => fileInput.click());
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });
    uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file && file.type.startsWith('image/')) handleFile(file);
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files[0]) handleFile(fileInput.files[0]);
    });

    function handleFile(file) {
        const reader = new FileReader();
        reader.onload = (e) => setImage(e.target.result);
        reader.readAsDataURL(file);
    }

    function setImage(dataUrl) {
        currentImage = dataUrl;
        previewImg.src = dataUrl;
        imagePreview.style.display = 'block';
        uploadZone.style.display = 'none';
        btnScan.disabled = false;
    }

    btnRemoveImage.addEventListener('click', () => {
        currentImage = null;
        imagePreview.style.display = 'none';
        uploadZone.style.display = '';
        btnScan.disabled = true;
        fileInput.value = '';
    });

    // ===================== Scan =====================
    btnScan.addEventListener('click', async () => {
        if (!currentImage) return;
        showLoading('Analizando billete con DeepSeek OCR...');
        try {
            const resp = await fetch('/api/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image: currentImage }),
            });
            const data = await resp.json();
            hideLoading();
            showResults(resultsPanel, data);
        } catch (err) {
            hideLoading();
            showResults(resultsPanel, { success: false, message: 'Error de conexion: ' + err.message });
        }
    });

    // ===================== Manual Verification =====================
    denomBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            denomBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedDenom = parseInt(btn.dataset.value);
        });
    });

    serialInput.addEventListener('input', () => {
        serialInput.value = serialInput.value.replace(/[^0-9]/g, '');
    });

    btnVerify.addEventListener('click', async () => {
        if (!selectedDenom) {
            alert('Seleccione la denominacion del billete.');
            return;
        }
        const serial = serialInput.value.trim();
        if (!serial || serial.length < 5) {
            alert('Ingrese un numero de serie valido (minimo 5 digitos).');
            return;
        }
        showLoading('Verificando numero de serie...');
        try {
            const resp = await fetch('/api/verify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ denomination: selectedDenom, serial: parseInt(serial) }),
            });
            const data = await resp.json();
            hideLoading();
            showResults(manualResultsPanel, data);
        } catch (err) {
            hideLoading();
            showResults(manualResultsPanel, { success: false, message: 'Error: ' + err.message });
        }
    });

    // ===================== Results Display =====================
    function showResults(panel, data) {
        if (!data.success) {
            panel.innerHTML = `
                <div class="result-card">
                    <div class="result-verdict sospechoso">
                        <div class="verdict-icon">&#9888;</div>
                        <div class="verdict-text sospechoso">ERROR</div>
                        <p style="margin-top:0.5rem;color:var(--text-secondary)">${data.message || 'No se pudo procesar.'}</p>
                        ${data.ocr_result && data.ocr_result.error ? `<p style="font-size:0.8rem;margin-top:0.5rem;color:var(--text-muted)">${data.ocr_result.error}</p>` : ''}
                    </div>
                </div>`;
            return;
        }

        const v = data.verdict;
        const vClass = v === 'ILEGAL' ? 'ilegal' : v === 'SOSPECHOSO' ? 'sospechoso' : 'legal';
        const vIcon = v === 'ILEGAL' ? '&#10060;' : v === 'SOSPECHOSO' ? '&#9888;' : '&#9989;';
        const confColor = v === 'ILEGAL' ? 'var(--danger)' : v === 'SOSPECHOSO' ? 'var(--warning)' : 'var(--success)';
        const confPct = Math.round(data.confidence * 100);

        let rangeInfo = '';
        if (data.db_check && data.db_check.matching_range) {
            const r = data.db_check.matching_range;
            rangeInfo = `
                <div class="detail-row">
                    <span class="detail-label">Rango ilegal</span>
                    <span class="detail-value" style="color:var(--danger)">${formatNumber(r.desde)} - ${formatNumber(r.hasta)}</span>
                </div>`;
        }

        let nnInfo = '';
        if (data.nn_prediction) {
            const nn = data.nn_prediction;
            if (nn.model_trained) {
                const nnPct = Math.round(nn.probability * 100);
                const nnColor = nnPct > 70 ? 'var(--danger)' : nnPct > 40 ? 'var(--warning)' : 'var(--success)';
                nnInfo = `
                    <div class="detail-row">
                        <span class="detail-label">Red Neuronal</span>
                        <span class="detail-value">
                            ${nnPct}% ilegal
                            <span class="confidence-bar"><span class="confidence-fill" style="width:${nnPct}%;background:${nnColor}"></span></span>
                        </span>
                    </div>`;
            } else {
                nnInfo = `
                    <div class="detail-row">
                        <span class="detail-label">Red Neuronal</span>
                        <span class="detail-value" style="color:var(--text-muted)">No entrenada</span>
                    </div>`;
            }
        }

        let ocrInfo = '';
        if (data.ocr_result) {
            ocrInfo = `
                <div class="detail-row">
                    <span class="detail-label">Fuente OCR</span>
                    <span class="detail-value">DeepSeek AI</span>
                </div>`;
        }

        panel.innerHTML = `
            <div class="result-card">
                <div class="result-verdict ${vClass}">
                    <div class="verdict-icon">${vIcon}</div>
                    <div class="verdict-text ${vClass}">${v}</div>
                    <p style="margin-top:0.5rem;font-size:0.9rem;color:var(--text-secondary)">
                        ${data.db_check ? data.db_check.message : ''}
                    </p>
                </div>
                <div class="result-details">
                    <div class="detail-row">
                        <span class="detail-label">Denominacion</span>
                        <span class="detail-value" style="color:var(--yellow)">Bs ${data.denomination}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">N&ordm; de Serie</span>
                        <span class="detail-value">${formatNumber(data.serial)}</span>
                    </div>
                    ${data.series ? `<div class="detail-row"><span class="detail-label">Serie</span><span class="detail-value">${data.series}</span></div>` : ''}
                    <div class="detail-row">
                        <span class="detail-label">Nivel de Riesgo</span>
                        <span class="detail-value" style="color:${confColor}">${data.risk_level}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Confianza</span>
                        <span class="detail-value">
                            ${confPct}%
                            <span class="confidence-bar"><span class="confidence-fill" style="width:${confPct}%;background:${confColor}"></span></span>
                        </span>
                    </div>
                    ${rangeInfo}
                    ${nnInfo}
                    ${ocrInfo}
                    <div class="detail-row">
                        <span class="detail-label">Referencia</span>
                        <span class="detail-value" style="font-size:0.75rem">${data.comunicado || 'CP9/2026'}</span>
                    </div>
                </div>
            </div>`;
    }

    // ===================== Training =====================
    btnTrain.addEventListener('click', async () => {
        const epochs = parseInt(document.getElementById('trainEpochs').value);
        const lr = parseFloat(document.getElementById('trainLR').value);
        const samples = parseInt(document.getElementById('trainSamples').value);

        btnTrain.disabled = true;
        trainingProgress.style.display = 'block';
        progressBar.style.width = '0%';
        progressText.textContent = 'Generando datos de entrenamiento...';

        // Simulate progress while waiting
        let pct = 0;
        const progressInterval = setInterval(() => {
            pct = Math.min(pct + 0.5, 90);
            progressBar.style.width = pct + '%';
            if (pct < 30) progressText.textContent = 'Generando datos sinteticos...';
            else if (pct < 70) progressText.textContent = `Entrenando red neuronal... (${Math.round(pct)}%)`;
            else progressText.textContent = 'Optimizando pesos...';
        }, 100);

        try {
            const resp = await fetch('/api/train', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ epochs, learning_rate: lr, samples }),
            });
            const data = await resp.json();
            clearInterval(progressInterval);
            progressBar.style.width = '100%';

            if (data.success) {
                progressText.textContent =
                    `Entrenamiento completado. Precision: ${(data.final_accuracy * 100).toFixed(1)}% | Loss: ${data.final_loss.toFixed(4)}`;
                drawCharts(data.history);
                loadModelInfo();
            } else {
                progressText.textContent = 'Error: ' + (data.message || 'Fallo el entrenamiento.');
            }
        } catch (err) {
            clearInterval(progressInterval);
            progressText.textContent = 'Error de conexion: ' + err.message;
        }
        btnTrain.disabled = false;
    });

    // ===================== Charts =====================
    function drawCharts(history) {
        if (!history) return;
        drawChart('lossChart', history.loss, '#EF4444', 'Loss');
        drawChart('accuracyChart', history.accuracy, '#22C55E', 'Accuracy');
    }

    function drawChart(canvasId, data, color, label) {
        const canvas = document.getElementById(canvasId);
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const padding = { top: 20, right: 20, bottom: 30, left: 50 };
        const chartW = w - padding.left - padding.right;
        const chartH = h - padding.top - padding.bottom;

        ctx.clearRect(0, 0, w, h);

        if (!data || data.length === 0) return;

        const minVal = Math.min(...data);
        const maxVal = Math.max(...data);
        const range = maxVal - minVal || 1;

        // Grid
        ctx.strokeStyle = '#2A2E3B';
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= 4; i++) {
            const y = padding.top + (chartH / 4) * i;
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(w - padding.right, y);
            ctx.stroke();

            ctx.fillStyle = '#6B7080';
            ctx.font = '10px Inter, sans-serif';
            ctx.textAlign = 'right';
            const val = maxVal - (range / 4) * i;
            ctx.fillText(val.toFixed(3), padding.left - 8, y + 4);
        }

        // Line
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';

        data.forEach((val, i) => {
            const x = padding.left + (i / (data.length - 1)) * chartW;
            const y = padding.top + chartH - ((val - minVal) / range) * chartH;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Fill under line
        const lastX = padding.left + chartW;
        const lastY = padding.top + chartH - ((data[data.length - 1] - minVal) / range) * chartH;
        ctx.lineTo(lastX, padding.top + chartH);
        ctx.lineTo(padding.left, padding.top + chartH);
        ctx.closePath();
        ctx.fillStyle = color + '15';
        ctx.fill();

        // X-axis label
        ctx.fillStyle = '#6B7080';
        ctx.font = '10px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Epocas', w / 2, h - 5);
        ctx.fillText('0', padding.left, h - 10);
        ctx.fillText(data.length.toString(), w - padding.right, h - 10);
    }

    // ===================== Model Info =====================
    async function loadModelInfo() {
        try {
            const resp = await fetch('/api/stats');
            const data = await resp.json();
            const nn = data.neural_network;
            document.getElementById('infoArch').textContent = nn.architecture || '-';
            document.getElementById('infoParams').textContent = nn.total_parameters ? nn.total_parameters.toLocaleString() : '-';
            document.getElementById('infoStatus').textContent = nn.trained ? 'Entrenado' : 'Sin entrenar';
            document.getElementById('infoStatus').style.color = nn.trained ? 'var(--success)' : 'var(--warning)';
            document.getElementById('infoAccuracy').textContent = nn.last_accuracy != null ? (nn.last_accuracy * 100).toFixed(1) + '%' : '-';
        } catch (e) { /* silent */ }
    }

    // ===================== Database View =====================
    async function loadDatabaseView() {
        try {
            const [rangesResp, statsResp] = await Promise.all([
                fetch('/api/ranges'),
                fetch('/api/stats'),
            ]);
            const ranges = await rangesResp.json();
            const stats = await statsResp.json();

            // Stats cards
            const grid = document.getElementById('statsGrid');
            const bcb = stats.bcb_database;
            grid.innerHTML = `
                <div class="stat-card">
                    <div class="stat-value">${bcb.total_rangos}</div>
                    <div class="stat-label">Rangos Ilegales</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${bcb.total_billetes_ilegales.toLocaleString()}</div>
                    <div class="stat-label">Billetes Ilegales</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${bcb['Bs50'] ? bcb['Bs50'].billetes_ilegales.toLocaleString() : '-'}</div>
                    <div class="stat-label">Bs50 Ilegales</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${bcb['Bs20'] ? bcb['Bs20'].billetes_ilegales.toLocaleString() : '-'}</div>
                    <div class="stat-label">Bs20 Ilegales</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${bcb['Bs10'] ? bcb['Bs10'].billetes_ilegales.toLocaleString() : '-'}</div>
                    <div class="stat-label">Bs10 Ilegales</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.total_scans}</div>
                    <div class="stat-label">Escaneos Realizados</div>
                </div>`;

            // Tables
            fillTable('tableBs50', ranges.filter(r => r.denomination === 50));
            fillTable('tableBs20', ranges.filter(r => r.denomination === 20));
            fillTable('tableBs10', ranges.filter(r => r.denomination === 10));
        } catch (e) { /* silent */ }
    }

    function fillTable(tbodyId, rows) {
        const tbody = document.getElementById(tbodyId);
        tbody.innerHTML = rows.map(r => `
            <tr>
                <td>${formatNumber(r.desde)}</td>
                <td>${formatNumber(r.hasta)}</td>
                <td>${r.cantidad.toLocaleString()}</td>
            </tr>
        `).join('');
    }

    // ===================== Helpers =====================
    function formatNumber(n) {
        return n ? n.toLocaleString('es-BO') : '-';
    }

    function showLoading(text) {
        loadingText.textContent = text || 'Procesando...';
        loadingOverlay.style.display = 'flex';
    }

    function hideLoading() {
        loadingOverlay.style.display = 'none';
    }

    // ===================== Init =====================
    loadModelInfo();
});
