/**
 * Dr. Billetes - Frontend Application
 * Detector de Billetes Ilegales BCB Bolivia
 * Powered by Sentinel AI
 */

document.addEventListener('DOMContentLoaded', () => {
    // ===================== State =====================
    let currentImage = null;
    let selectedDenom = null;
    let cameraStream = null;
    let cameraPermissionGranted = false;

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
    const scanContainer = document.getElementById('scanContainer');
    const capturePreview = document.getElementById('capturePreview');
    const capturePreviewImg = document.getElementById('capturePreviewImg');
    const captureLoading = document.getElementById('captureLoading');

    const denomBtns = document.querySelectorAll('.denom-btn');
    const serialInput = document.getElementById('serialInput');
    const btnVerify = document.getElementById('btnVerify');
    const manualResultsPanel = document.getElementById('manualResultsPanel');
    const manualContainer = document.getElementById('manualContainer');

    const btnTrain = document.getElementById('btnTrain');
    const trainingProgress = document.getElementById('trainingProgress');
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');

    const loadingOverlay = document.getElementById('loadingOverlay');
    const loadingText = document.getElementById('loadingText');

    // Stats banner elements
    const statTotal = document.getElementById('statTotal');
    const statIllegal = document.getElementById('statIllegal');
    const statLegal = document.getElementById('statLegal');

    // ===================== Tabs =====================
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.tab;
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(tc => tc.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(`tab-${target}`).classList.add('active');

            if (target === 'scan') {
                if (cameraStream && cameraStream.active && !currentImage) {
                    showCameraActive();
                } else if (cameraPermissionGranted && !currentImage) {
                    startCamera();
                }
            } else {
                pauseCamera();
            }
            if (target === 'stats') loadChartData();
            if (target === 'database') loadDatabaseView();
            if (target === 'training') loadModelInfo();
        });
    });

    // ===================== Stats Banner =====================
    async function loadStats() {
        try {
            const resp = await fetch('/api/stats');
            const data = await resp.json();
            if (statTotal) statTotal.textContent = data.total_scans || 0;
            if (statIllegal) statIllegal.textContent = data.illegal_count || 0;
            if (statLegal) statLegal.textContent = data.legal_count || 0;
            const statSuspicious = document.getElementById('statSuspicious');
            if (statSuspicious) statSuspicious.textContent = data.suspicious_count || 0;
        } catch (e) { /* silent */ }
    }

    // ===================== Camera =====================
    cameraOverlay.addEventListener('click', startCamera);
    btnStartCamera.addEventListener('click', startCamera);
    const btnRecapture = document.getElementById('btnRecapture');
    const cameraGuide = document.getElementById('cameraGuide');

    async function checkCameraPermission() {
        try {
            if (navigator.permissions && navigator.permissions.query) {
                const result = await navigator.permissions.query({ name: 'camera' });
                cameraPermissionGranted = result.state === 'granted';
                result.addEventListener('change', () => {
                    cameraPermissionGranted = result.state === 'granted';
                });
            }
        } catch (e) { /* Firefox doesn't support camera permission query */ }
    }

    async function startCamera() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            const isLocalhost = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
            if (!isLocalhost) {
                alert('La camara requiere HTTPS.\n\nAcceda desde https://dr.sentinel-ia.com o suba una imagen.');
            } else {
                alert('Su navegador no soporta acceso a la camara.');
            }
            return;
        }

        // Reuse existing active stream
        if (cameraStream && cameraStream.active) {
            cameraVideo.srcObject = cameraStream;
            showCameraActive();
            return;
        }

        try {
            cameraStream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
            });
            cameraVideo.srcObject = cameraStream;
            cameraPermissionGranted = true;
            showCameraActive();
        } catch (err) {
            if (err.name === 'NotAllowedError') {
                cameraPermissionGranted = false;
            }
            alert('No se pudo acceder a la camara: ' + err.message + '\n\nUse la opcion de subir imagen.');
        }
    }

    function showCameraActive() {
        cameraVideo.play();
        cameraOverlay.classList.add('hidden');
        cameraContainer.querySelector('.camera-frame').classList.add('active');
        if (cameraGuide) cameraGuide.style.display = '';
        cameraContainer.style.borderStyle = 'solid';
        btnCapture.disabled = false;
        btnStartCamera.style.display = 'none';
        // Reset preview state
        imagePreview.style.display = 'none';
        uploadZone.style.display = '';
        if (btnRecapture) btnRecapture.style.display = 'none';
        btnScan.disabled = true;
    }

    btnCapture.addEventListener('click', async () => {
        if (!cameraStream) return;
        // Resize to max 1280px to keep image small for OCR
        const maxDim = 1280;
        let w = cameraVideo.videoWidth;
        let h = cameraVideo.videoHeight;
        if (w > maxDim || h > maxDim) {
            const scale = maxDim / Math.max(w, h);
            w = Math.round(w * scale);
            h = Math.round(h * scale);
        }
        cameraCanvas.width = w;
        cameraCanvas.height = h;
        const ctx = cameraCanvas.getContext('2d');
        ctx.drawImage(cameraVideo, 0, 0, w, h);
        const dataUrl = cameraCanvas.toDataURL('image/jpeg', 0.85);
        currentImage = dataUrl;

        // Show captured image in-place inside camera container
        capturePreviewImg.src = dataUrl;
        capturePreview.style.display = 'flex';
        captureLoading.style.display = 'flex';
        pauseCamera();

        // Hide upload zone and divider
        uploadZone.style.display = 'none';
        const divider = document.querySelector('.divider');
        if (divider) divider.style.display = 'none';
        btnScan.style.display = 'none';
        btnCapture.disabled = true;
        if (btnRecapture) btnRecapture.style.display = '';

        // Auto-analyze with progressive messages
        const captureText = captureLoading.querySelector('p');
        const captureMessages = ['Analizando billete...', 'Procesando con IA...', 'Extrayendo datos...', 'Casi listo...'];
        let ci = 0;
        const captureInterval = setInterval(() => {
            ci++;
            if (ci < captureMessages.length && captureText) captureText.textContent = captureMessages[ci];
        }, 5000);
        try {
            const resp = await fetch('/api/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image: currentImage }),
            });
            const data = await resp.json();
            clearInterval(captureInterval);
            captureLoading.style.display = 'none';
            showResults(resultsPanel, data, scanContainer);
            loadStats();
        } catch (err) {
            clearInterval(captureInterval);
            captureLoading.style.display = 'none';
            showResults(resultsPanel, { success: false, message: 'Error de conexion: ' + err.message }, scanContainer);
        }
    });

    if (btnRecapture) {
        btnRecapture.addEventListener('click', () => {
            currentImage = null;
            capturePreview.style.display = 'none';
            captureLoading.style.display = 'none';
            imagePreview.style.display = 'none';
            uploadZone.style.display = '';
            const divider = document.querySelector('.divider');
            if (divider) divider.style.display = '';
            btnScan.style.display = '';
            btnScan.disabled = true;
            btnRecapture.style.display = 'none';
            if (scanContainer) scanContainer.classList.remove('has-results');
            startCamera();
        });
    }

    function pauseCamera() {
        // Keep stream alive, just hide camera UI
        cameraVideo.pause();
        cameraOverlay.classList.add('hidden');
        cameraContainer.querySelector('.camera-frame').classList.remove('active');
        if (cameraGuide) cameraGuide.style.display = 'none';
        btnCapture.disabled = true;
    }

    function stopCamera() {
        if (cameraStream) {
            cameraStream.getTracks().forEach(t => t.stop());
            cameraStream = null;
        }
        cameraOverlay.classList.remove('hidden');
        cameraContainer.querySelector('.camera-frame').classList.remove('active');
        if (cameraGuide) cameraGuide.style.display = 'none';
        cameraContainer.style.borderStyle = 'dashed';
        btnCapture.disabled = true;
        btnStartCamera.style.display = '';
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
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                const maxDim = 1280;
                let w = img.naturalWidth;
                let h = img.naturalHeight;
                if (w > maxDim || h > maxDim) {
                    const scale = maxDim / Math.max(w, h);
                    w = Math.round(w * scale);
                    h = Math.round(h * scale);
                }
                const canvas = document.createElement('canvas');
                canvas.width = w;
                canvas.height = h;
                canvas.getContext('2d').drawImage(img, 0, 0, w, h);
                setImage(canvas.toDataURL('image/jpeg', 0.85));
            };
            img.src = e.target.result;
        };
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
        const stopProgress = showLoadingWithProgress('Preparando imagen...');
        try {
            const resp = await fetch('/api/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image: currentImage }),
            });
            const data = await resp.json();
            stopProgress();
            showResults(resultsPanel, data, scanContainer);
            loadStats();
        } catch (err) {
            stopProgress();
            showResults(resultsPanel, { success: false, message: 'Error de conexion: ' + err.message }, scanContainer);
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
            showResults(manualResultsPanel, data, manualContainer);
            loadStats();
        } catch (err) {
            hideLoading();
            showResults(manualResultsPanel, { success: false, message: 'Error: ' + err.message }, manualContainer);
        }
    });

    // ===================== Reset Scan =====================
    function resetScan(container) {
        // Limpiar imagen en memoria
        currentImage = null;

        // Limpiar previews
        if (previewImg) previewImg.src = '';
        if (capturePreviewImg) capturePreviewImg.src = '';
        if (imagePreview) imagePreview.style.display = 'none';
        if (capturePreview) capturePreview.style.display = 'none';
        if (uploadZone) uploadZone.style.display = '';
        if (fileInput) fileInput.value = '';
        if (btnScan) btnScan.disabled = true;
        if (resultsPanel) resultsPanel.innerHTML = '';

        // Quitar clase de resultados
        if (container) container.classList.remove('has-results');
    }

    // Make available globally for inline onclick
    window.resetScan = function(containerId) {
        const el = document.getElementById(containerId);
        resetScan(el);
    };

    // ===================== Results Display =====================
    function showResults(panel, data, container) {
        // Add has-results class for mobile layout
        if (container) container.classList.add('has-results');

        if (!data.success) {
            const noBanknotes = data.no_banknotes;
            const isOcrError = data.step_failed === 'ocr' && !noBanknotes;
            const errorMsg = data.message || data.error || 'No se pudo procesar.';

            let errorIcon, errorTitle, extraContent;
            if (noBanknotes) {
                errorIcon = '&#128181;';
                errorTitle = 'SIN BILLETES';
                extraContent = '<p style="margin-top:0.5rem;color:var(--text-secondary);font-size:0.85rem">Intente con una foto mas clara donde los billetes sean visibles.</p>';
            } else if (isOcrError) {
                errorIcon = '&#128269;';
                errorTitle = 'ERROR OCR';
                extraContent = `
                    <p style="margin-top:1rem;color:var(--text-secondary);font-size:0.85rem">Puede verificar el billete manualmente:</p>
                    <button onclick="document.querySelector('[data-tab=manual]').click()" style="margin-top:0.8rem;padding:0.7rem 1.5rem;background:var(--red);color:white;border:none;border-radius:8px;font-weight:600;font-size:0.9rem;cursor:pointer">
                        Verificar Manual
                    </button>`;
            } else {
                errorIcon = '&#9888;';
                errorTitle = 'ERROR';
                extraContent = '';
            }

            panel.innerHTML = `
                <div class="result-card">
                    <div class="result-verdict sospechoso">
                        <div class="verdict-icon">${errorIcon}</div>
                        <div class="verdict-text sospechoso">${errorTitle}</div>
                        <p style="margin-top:0.5rem;color:var(--text-secondary)">${errorMsg}</p>
                        ${extraContent}
                    </div>
                    <button class="scan-another-btn" onclick="resetScan('${container ? container.id : ''}')">
                        &#8592; Escanear otro billete
                    </button>
                </div>`;
            scrollToResults(panel);
            return;
        }

        const banknotes = data.banknotes || [data];
        const isMulti = banknotes.length > 1;
        let html = '';

        // Batch summary for multi-banknote
        if (isMulti && data.summary) {
            const s = data.summary;
            html += `<div class="batch-summary">
                <h3>${s.total} billetes detectados</h3>
                <div class="batch-counts">
                    ${s.legal > 0 ? `<span class="batch-count legal">${s.legal} Legal${s.legal > 1 ? 'es' : ''}</span>` : ''}
                    ${s.illegal > 0 ? `<span class="batch-count ilegal">${s.illegal} Ilegal${s.illegal > 1 ? 'es' : ''}</span>` : ''}
                    ${s.suspicious > 0 ? `<span class="batch-count sospechoso">${s.suspicious} Sospechoso${s.suspicious > 1 ? 's' : ''}</span>` : ''}
                </div>
            </div>`;
        }

        // Render each banknote card
        banknotes.forEach((bn, idx) => {
            html += buildBanknoteCard(bn, idx, banknotes.length, container);
        });

        // Share section (once at the end)
        const firstBn = banknotes[0];
        const shareText = isMulti
            ? `Verifique ${banknotes.length} billetes: ${data.summary.illegal} ilegales, ${data.summary.legal} legales. Dr. Billetes BCB CP9/2026:`
            : firstBn.verdict === 'ILEGAL'
            ? `Mi billete de Bs${firstBn.denomination} (serie ${formatNumber(firstBn.serial)}) es ILEGAL segun el BCB CP9/2026. Verifica tus billetes en:`
            : firstBn.verdict === 'SOSPECHOSO'
            ? `Mi billete de Bs${firstBn.denomination} salio SOSPECHOSO. Verifica tus billetes bolivianos aqui:`
            : `Mi billete de Bs${firstBn.denomination} es LEGAL. Verifica tus billetes bolivianos aqui:`;
        const shareUrl = 'https://dr.sentinel-ia.com';

        html += `
            <div class="share-section">
                <p class="share-label">Compartir resultado</p>
                <div class="share-buttons">
                    <a class="share-btn whatsapp" href="https://wa.me/?text=${encodeURIComponent(shareText + ' ' + shareUrl)}" target="_blank" rel="noopener">WhatsApp</a>
                    <a class="share-btn" href="https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(shareUrl)}&quote=${encodeURIComponent(shareText)}" target="_blank" rel="noopener">Facebook</a>
                    <a class="share-btn" href="https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(shareUrl)}" target="_blank" rel="noopener">X</a>
                    <button class="share-btn" onclick="navigator.clipboard.writeText('${shareText.replace(/'/g, "\\'")} ${shareUrl}').then(()=>this.textContent='Copiado!')">Copiar</button>
                </div>
            </div>
            <button class="scan-another-btn" onclick="resetScan('${container ? container.id : ''}')">
                &#8592; Escanear otro billete
            </button>`;

        panel.innerHTML = html;
        scrollToResults(panel);
    }

    function buildBanknoteCard(bn, index, total, container) {
        const isMulti = total > 1;
        const v = bn.verdict;
        const vClass = v === 'ILEGAL' ? 'ilegal' : v === 'SOSPECHOSO' ? 'sospechoso' : 'legal';
        const vIcon = v === 'ILEGAL' ? '&#10060;' : v === 'SOSPECHOSO' ? '&#9888;' : '&#9989;';
        const confColor = v === 'ILEGAL' ? 'var(--danger)' : v === 'SOSPECHOSO' ? 'var(--warning)' : 'var(--success)';
        const confPct = Math.round(bn.confidence * 100);

        let rangeInfo = '';
        if (bn.db_check && bn.db_check.matching_range) {
            const r = bn.db_check.matching_range;
            rangeInfo = `
                <div class="detail-row">
                    <span class="detail-label">Rango ilegal</span>
                    <span class="detail-value" style="color:var(--danger)">${formatNumber(r.desde)} - ${formatNumber(r.hasta)}</span>
                </div>`;
        }

        let nnInfo = '';
        if (bn.nn_prediction && bn.nn_prediction.model_trained) {
            const nnPct = Math.round(bn.nn_prediction.probability * 100);
            const nnColor = nnPct > 70 ? 'var(--danger)' : nnPct > 40 ? 'var(--warning)' : 'var(--success)';
            nnInfo = `
                <div class="detail-row">
                    <span class="detail-label">Red Neuronal</span>
                    <span class="detail-value">
                        ${nnPct}% ilegal
                        <span class="confidence-bar"><span class="confidence-fill" style="width:${nnPct}%;background:${nnColor}"></span></span>
                    </span>
                </div>`;
        }

        return `
            <div class="result-card${isMulti ? ' compact' : ''}">
                ${isMulti ? `<span class="banknote-index">Billete ${index + 1} de ${total}</span>` : ''}
                <div class="result-verdict ${vClass}">
                    <div class="verdict-icon">${vIcon}</div>
                    <div class="verdict-text ${vClass}">${v}</div>
                    <p style="margin-top:0.5rem;font-size:0.85rem;color:var(--text-secondary)">
                        ${bn.db_check ? bn.db_check.message : ''}
                    </p>
                </div>
                <div class="result-details">
                    <div class="detail-row">
                        <span class="detail-label">Denominacion</span>
                        <span class="detail-value" style="color:var(--red)">Bs ${bn.denomination}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">N&ordm; de Serie</span>
                        <span class="detail-value">${formatNumber(bn.serial)}</span>
                    </div>
                    ${bn.series ? `<div class="detail-row"><span class="detail-label">Serie</span><span class="detail-value">${bn.series}</span></div>` : ''}
                    <div class="detail-row">
                        <span class="detail-label">Nivel de Riesgo</span>
                        <span class="detail-value" style="color:${confColor}">${bn.risk_level}</span>
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
                    ${!isMulti && bn.ocr_result ? `<div class="detail-row"><span class="detail-label">Fuente OCR</span><span class="detail-value">OCR Sentinel AI</span></div>` : ''}
                    <div class="detail-row">
                        <span class="detail-label">Referencia</span>
                        <span class="detail-value" style="font-size:0.75rem">${bn.comunicado || 'CP9/2026'}</span>
                    </div>
                </div>
            </div>`;
    }

    function scrollToResults(panel) {
        if (window.innerWidth <= 900) {
            setTimeout(() => {
                panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 100);
        }
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
        drawChart('lossChart', history.loss, '#DC2626', 'Loss');
        drawChart('accuracyChart', history.accuracy, '#16A34A', 'Accuracy');
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
        ctx.strokeStyle = '#E2E5EB';
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= 4; i++) {
            const y = padding.top + (chartH / 4) * i;
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(w - padding.right, y);
            ctx.stroke();

            ctx.fillStyle = '#8B90A0';
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
        ctx.lineTo(lastX, padding.top + chartH);
        ctx.lineTo(padding.left, padding.top + chartH);
        ctx.closePath();
        ctx.fillStyle = color + '15';
        ctx.fill();

        // X-axis label
        ctx.fillStyle = '#8B90A0';
        ctx.font = '10px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Epocas', w / 2, h - 5);
        ctx.fillText('0', padding.left, h - 10);
        ctx.fillText(data.length.toString(), w - padding.right, h - 10);
    }

    // ===================== Usage Stats Charts =====================
    async function loadChartData() {
        try {
            const resp = await fetch('/api/stats/chart?days=7');
            const data = await resp.json();
            // Wait for next frame to ensure tab is fully rendered
            requestAnimationFrame(() => {
                drawDetectionsChart(data);
                drawTokensChart(data);
            });
        } catch (e) { /* silent */ }
    }

    function drawMultiLineChart(canvasId, labels, datasets) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !labels.length) return;

        const dpr = window.devicePixelRatio || 1;
        // Usar getBoundingClientRect para respetar CSS width:100% sin causar overflow
        const w = Math.floor(canvas.getBoundingClientRect().width);
        if (w < 50) return; // Tab oculto o no renderizado
        const h = 200;

        canvas.width = w * dpr;
        canvas.height = h * dpr;
        // No establecer style.width — CSS width:100% lo controla sin overflow
        canvas.style.height = h + 'px';

        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        const margin = { top: 15, right: 15, bottom: 35, left: 45 };
        const chartW = w - margin.left - margin.right;
        const chartH = h - margin.top - margin.bottom;

        let maxVal = 0;
        datasets.forEach(ds => {
            ds.data.forEach(v => { if (v > maxVal) maxVal = v; });
        });
        if (maxVal === 0) maxVal = 1;
        const niceMax = Math.ceil(maxVal * 1.1) || 1;

        ctx.clearRect(0, 0, w, h);

        // Grid horizontal
        ctx.strokeStyle = 'rgba(128,128,128,0.15)';
        ctx.lineWidth = 1;
        const gridLines = 4;
        for (let i = 0; i <= gridLines; i++) {
            const y = margin.top + (chartH * i / gridLines);
            ctx.beginPath();
            ctx.moveTo(margin.left, y);
            ctx.lineTo(margin.left + chartW, y);
            ctx.stroke();

            const val = Math.round(niceMax * (1 - i / gridLines));
            ctx.fillStyle = 'rgba(128,128,128,0.6)';
            ctx.font = '10px system-ui, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(val >= 1000 ? (val / 1000).toFixed(1) + 'k' : val.toString(), margin.left - 6, y + 3);
        }

        // Labels X — ~7 etiquetas max
        const months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
        const step = Math.max(1, Math.ceil(labels.length / 7));
        ctx.textAlign = 'center';
        ctx.fillStyle = 'rgba(128,128,128,0.6)';
        ctx.font = '10px system-ui, sans-serif';
        for (let i = 0; i < labels.length; i += step) {
            const x = margin.left + (chartW * i / (labels.length - 1 || 1));
            const parts = labels[i].split('-');
            const label = parseInt(parts[2]) + ' ' + months[parseInt(parts[1]) - 1];
            ctx.fillText(label, x, h - 5);
        }
        // Siempre mostrar ultima fecha
        if (labels.length > 1 && (labels.length - 1) % step !== 0) {
            const x = margin.left + chartW;
            const parts = labels[labels.length - 1].split('-');
            const label = parseInt(parts[2]) + ' ' + months[parseInt(parts[1]) - 1];
            ctx.fillText(label, x, h - 5);
        }

        // Lineas de datos
        const n = labels.length;
        datasets.forEach(ds => {
            ctx.strokeStyle = ds.color;
            ctx.lineWidth = 2;
            ctx.lineJoin = 'round';
            ctx.beginPath();

            ds.data.forEach((val, i) => {
                const x = n === 1 ? margin.left + chartW / 2 : margin.left + (i / (n - 1)) * chartW;
                const y = margin.top + chartH - (chartH * val / niceMax);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();

            // Area fill
            if (n > 1) {
                ctx.lineTo(margin.left + chartW, margin.top + chartH);
                ctx.lineTo(margin.left, margin.top + chartH);
                ctx.closePath();
                ctx.fillStyle = ds.color + '15';
                ctx.fill();
            }

            // Puntos en dias con datos
            ds.data.forEach((val, i) => {
                if (val > 0) {
                    const x = n === 1 ? margin.left + chartW / 2 : margin.left + (i / (n - 1)) * chartW;
                    const y = margin.top + chartH - (chartH * val / niceMax);
                    ctx.fillStyle = ds.color;
                    ctx.beginPath();
                    ctx.arc(x, y, 3, 0, Math.PI * 2);
                    ctx.fill();
                }
            });
        });
    }

    function drawDetectionsChart(data) {
        if (!data.days || !data.days.length) return;
        drawMultiLineChart('detectionsChart', data.days, [
            { data: data.legal, color: '#22c55e' },
            { data: data.illegal, color: '#ef4444' },
            { data: data.suspicious, color: '#f59e0b' },
        ]);
    }

    function drawTokensChart(data) {
        if (!data.days || !data.days.length) return;
        drawMultiLineChart('tokensChart', data.days, [
            { data: data.tokens, color: '#3b82f6' },
        ]);
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

            fillTable('tableBs50', ranges.filter(r => r.denomination === 50));
            fillTable('tableBs20', ranges.filter(r => r.denomination === 20));
            fillTable('tableBs10', ranges.filter(r => r.denomination === 10));
            loadHistory(1);
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

    function showLoadingWithProgress(initialText) {
        const messages = [
            'Preparando imagen...',
            'Enviando al servidor OCR...',
            'Analizando con inteligencia artificial...',
            'Procesando con modelo de vision...',
            'Extrayendo datos del billete...',
            'Casi listo...',
        ];
        let idx = 0;
        loadingText.textContent = initialText || messages[0];
        loadingOverlay.style.display = 'flex';
        const interval = setInterval(() => {
            idx++;
            if (idx < messages.length) loadingText.textContent = messages[idx];
        }, 4000);
        return () => { clearInterval(interval); loadingOverlay.style.display = 'none'; };
    }

    // ===================== Page Lifecycle =====================
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            pauseCamera();
        } else {
            const scanTab = document.querySelector('.tab.active');
            if (scanTab?.dataset.tab === 'scan' && cameraStream?.active && !currentImage) {
                showCameraActive();
            }
        }
    });

    window.addEventListener('beforeunload', () => {
        stopCamera();
    });

    // ===================== History =====================
    let historyPage = 1;

    async function loadHistory(page) {
        historyPage = page || 1;
        const container = document.getElementById('historyContainer');
        const pagination = document.getElementById('historyPagination');
        if (!container) return;

        try {
            const resp = await fetch(`/api/history?page=${historyPage}&per_page=15`);
            const data = await resp.json();

            if (!data.scans || data.scans.length === 0) {
                container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:2rem">No hay escaneos registrados aun.</p>';
                if (pagination) pagination.innerHTML = '';
                return;
            }

            let html = '<table class="data-table history-table"><thead><tr>';
            html += '<th>Fecha</th><th>Bs</th><th>Serie</th><th>Veredicto</th><th>Metodo</th>';
            html += '</tr></thead><tbody>';

            data.scans.forEach(s => {
                const date = new Date(s.timestamp).toLocaleString('es-BO', { dateStyle: 'short', timeStyle: 'short' });
                const vClass = s.verdict === 'ILEGAL' ? 'color:var(--danger)' : s.verdict === 'SOSPECHOSO' ? 'color:var(--warning)' : 'color:var(--success)';
                html += `<tr>
                    <td>${date}</td>
                    <td>${s.denomination || '-'}</td>
                    <td>${s.series || '-'}</td>
                    <td style="${vClass};font-weight:600">${s.verdict}</td>
                    <td>${s.method}</td>
                </tr>`;
            });

            html += '</tbody></table>';
            container.innerHTML = html;

            if (pagination && data.total_pages > 1) {
                let pagHtml = '';
                pagHtml += `<button class="btn-page" ${data.page <= 1 ? 'disabled' : ''} onclick="window._loadHistory(${data.page - 1})">Anterior</button>`;
                pagHtml += `<span class="pagination-info">Pagina ${data.page} de ${data.total_pages}</span>`;
                pagHtml += `<button class="btn-page" ${data.page >= data.total_pages ? 'disabled' : ''} onclick="window._loadHistory(${data.page + 1})">Siguiente</button>`;
                pagination.innerHTML = pagHtml;
            } else if (pagination) {
                pagination.innerHTML = '';
            }
        } catch (e) {
            container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:1rem">Error al cargar historial.</p>';
        }
    }

    window._loadHistory = function(page) { loadHistory(page); };

    // ===================== Init =====================
    loadStats();
    loadModelInfo();
    checkCameraPermission().then(() => {
        if (cameraPermissionGranted) startCamera();
    });

    // ===================== Donate Modal =====================
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeDonateModal();
    });
});

function openDonateModal() {
    document.getElementById('donateOverlay').classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeDonateModal() {
    document.getElementById('donateOverlay').classList.remove('active');
    document.body.style.overflow = '';
}

function switchDonateTab(tab) {
    document.querySelectorAll('.donate-tab').forEach(function(btn) {
        btn.classList.remove('active');
    });
    document.querySelectorAll('.donate-panel').forEach(function(panel) {
        panel.classList.remove('active');
    });
    // Activate clicked tab
    var tabs = document.querySelectorAll('.donate-tab');
    var tabMap = { bcp: 0, binance: 1, meru: 2 };
    if (tabMap[tab] !== undefined) {
        tabs[tabMap[tab]].classList.add('active');
    }
    var panel = document.getElementById('donate-' + tab);
    if (panel) panel.classList.add('active');
}
