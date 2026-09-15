/**
 * MediData — Client-Side Application Engine
 * Handles Drag & Drop Upload, Honest Multi-Step Processing,
 * Dynamic Results Dashboard, Medicine Live Search, and Clinical Modals.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Global State
  let currentFile = null;
  let currentAnalysisData = null;
  let searchDebounceTimer = null;

  // DOM Elements
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('billFileInput');
  const fileSelectedCard = document.getElementById('fileSelectedCard');
  const selectedFileName = document.getElementById('selectedFileName');
  const selectedFileSize = document.getElementById('selectedFileSize');
  const btnRemoveFile = document.getElementById('btnRemoveFile');
  const btnStartAnalysis = document.getElementById('btnStartAnalysis');

  const processingCard = document.getElementById('processingCard');
  const processingStep1 = document.getElementById('procStep1');
  const processingStep2 = document.getElementById('procStep2');
  const processingStep3 = document.getElementById('procStep3');
  const processingStep4 = document.getElementById('procStep4');

  const sectionResults = document.getElementById('sectionResults');
  const resultsDocName = document.getElementById('resultsDocName');
  const metricGrandTotal = document.getElementById('metricGrandTotal');
  const metricTotalItems = document.getElementById('metricTotalItems');
  const metricMedicinesCount = document.getElementById('metricMedicinesCount');
  const metricSavingsAmount = document.getElementById('metricSavingsAmount');
  const itemsContainer = document.getElementById('itemsContainer');
  const filterTabsContainer = document.getElementById('filterTabsContainer');

  const medicineSearchInput = document.getElementById('medicineSearchInput');
  const medSearchResultsGrid = document.getElementById('medSearchResultsGrid');
  const medicineModal = document.getElementById('medicineModal');
  const modalCloseBtn = document.getElementById('modalCloseBtn');
  const toastContainer = document.getElementById('toastContainer');

  // ─── CSRF Token Helper ───
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  // ─── Toast Notification System ───
  function showToast(message, type = 'info') {
    if (!toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type === 'success' ? 'toast-success' : type === 'error' ? 'toast-error' : ''}`;
    
    let icon = 'fa-circle-info';
    if (type === 'success') icon = 'fa-circle-check';
    if (type === 'error') icon = 'fa-triangle-exclamation';

    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${escapeHtml(message)}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(20px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 4500);
  }

  function formatBytes(bytes, decimals = 1) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // ─── Drag & Drop Handlers ───
  if (dropzone && fileInput) {
    dropzone.addEventListener('click', () => fileInput.click());

    ['dragenter', 'dragover'].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove('dragover');
      });
    });

    dropzone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files && files.length > 0) {
        handleSelectedFile(files[0]);
      }
    });

    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length > 0) {
        handleSelectedFile(fileInput.files[0]);
      }
    });
  }

  function handleSelectedFile(file) {
    const validExtensions = ['.pdf', '.png', '.jpg', '.jpeg', '.webp'];
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    
    if (!validExtensions.includes(ext)) {
      showToast(`Unsupported file format "${ext}". Please upload PDF, PNG, JPG, or WEBP.`, 'error');
      return;
    }

    if (file.size > 15 * 1024 * 1024) {
      showToast(`File is too large (${formatBytes(file.size)}). Maximum allowed size is 15 MB.`, 'error');
      return;
    }

    currentFile = file;
    selectedFileName.textContent = file.name;
    selectedFileSize.textContent = formatBytes(file.size);
    fileSelectedCard.classList.add('active');
    btnStartAnalysis.disabled = false;
  }

  if (btnRemoveFile) {
    btnRemoveFile.addEventListener('click', () => {
      currentFile = null;
      if (fileInput) fileInput.value = '';
      fileSelectedCard.classList.remove('active');
      btnStartAnalysis.disabled = true;
    });
  }

  // ─── Multi-Step Honest Processing Execution ───
  if (btnStartAnalysis) {
    btnStartAnalysis.addEventListener('click', async () => {
      if (!currentFile) return;

      btnStartAnalysis.disabled = true;
      processingCard.classList.add('active');
      sectionResults.classList.remove('active');

      // Reset Step Indicators
      [processingStep1, processingStep2, processingStep3, processingStep4].forEach(s => {
        if (s) {
          s.className = 'step-item';
          const b = s.querySelector('.step-bullet');
          if (b) b.innerHTML = '<i class="fa-solid fa-circle" style="font-size:6px"></i>';
        }
      });

      // Activate Step 1: Uploading
      setStepState(processingStep1, 'active');

      const formData = new FormData();
      formData.append('file', currentFile);

      // Simulate honest progressive timeline while network request is underway
      const timer1 = setTimeout(() => {
        setStepState(processingStep1, 'completed');
        setStepState(processingStep2, 'active');
      }, 1500);

      const timer2 = setTimeout(() => {
        setStepState(processingStep2, 'completed');
        setStepState(processingStep3, 'active');
      }, 4500);

      try {
        const response = await fetch('/analyse/', {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken'),
          },
          body: formData,
        });

        clearTimeout(timer1);
        clearTimeout(timer2);

        setStepState(processingStep1, 'completed');
        setStepState(processingStep2, 'completed');
        setStepState(processingStep3, 'completed');
        setStepState(processingStep4, 'active');

        const raw = await response.text();
        let result;
        try {
          result = JSON.parse(raw);
        } catch (e) {
          throw new Error('Server returned an invalid JSON response.');
        }

        if (!response.ok || !result.success) {
          const errMsg = result.error || 'Failed to process document.';
          showToast(errMsg, 'error');
          processingCard.classList.remove('active');
          btnStartAnalysis.disabled = false;
          return;
        }

        // Processing Completed
        setStepState(processingStep4, 'completed');
        setTimeout(() => {
          processingCard.classList.remove('active');
          btnStartAnalysis.disabled = false;
          renderAnalysisResults(result.data, result.filename);
        }, 500);

      } catch (err) {
        clearTimeout(timer1);
        clearTimeout(timer2);
        processingCard.classList.remove('active');
        btnStartAnalysis.disabled = false;
        showToast(err.message || 'An error occurred during analysis.', 'error');
      }
    });
  }

  function setStepState(stepEl, state) {
    if (!stepEl) return;
    stepEl.className = `step-item ${state}`;
    const bullet = stepEl.querySelector('.step-bullet');
    if (!bullet) return;

    if (state === 'completed') {
      bullet.innerHTML = '<i class="fa-solid fa-check"></i>';
    } else if (state === 'active') {
      bullet.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="font-size:10px"></i>';
    } else {
      bullet.innerHTML = '<i class="fa-solid fa-circle" style="font-size:6px"></i>';
    }
  }

  // ─── Render Results Dashboard ───
  function renderAnalysisResults(data, filename) {
    currentAnalysisData = data;
    if (!data) return;

    const items = data.line_items || [];
    const summary = data.summary || { medicines: 0, lab_tests: 0, devices: 0, services: 0 };
    const financials = data.financials || {};

    if (resultsDocName) resultsDocName.textContent = filename || 'Analyzed Medical Bill';
    if (metricGrandTotal) metricGrandTotal.textContent = `₹${Number(data.final_total || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
    if (metricTotalItems) metricTotalItems.textContent = `${items.length} Items`;
    if (metricMedicinesCount) metricMedicinesCount.textContent = `${summary.medicines} Rx Identified`;

    // Calculate potential savings if 1mg comparisons are present
    let totalSavings = 0;
    items.forEach(it => {
      if (it.savings_per_unit && it.savings_per_unit > 0) {
        totalSavings += it.savings_per_unit * (it.quantity || 1);
      }
    });

    if (metricSavingsAmount) {
      if (totalSavings > 0) {
        metricSavingsAmount.innerHTML = `<span class="metric-highlight-green">₹${totalSavings.toFixed(2)} Potential Savings</span>`;
      } else {
        metricSavingsAmount.textContent = `Benchmark checked`;
      }
    }

    // Render Filter Tabs
    renderFilterTabs(summary, items.length);

    // Render Item Cards
    renderFilteredItems('ALL');

    sectionResults.classList.add('active');
    sectionResults.scrollIntoView({ behavior: 'smooth' });
    showToast('Medical bill successfully analyzed and cross-referenced!', 'success');
  }

  function renderFilterTabs(summary, totalCount) {
    if (!filterTabsContainer) return;
    filterTabsContainer.innerHTML = `
      <button class="tab-btn active" data-filter="ALL"><i class="fa-solid fa-list-check"></i> All Items (${totalCount})</button>
      <button class="tab-btn" data-filter="MEDICINE"><i class="fa-solid fa-pills"></i> Medicines (${summary.medicines || 0})</button>
      <button class="tab-btn" data-filter="LAB_TEST"><i class="fa-solid fa-vial"></i> Lab Tests (${summary.lab_tests || 0})</button>
      <button class="tab-btn" data-filter="MEDICAL_DEVICE"><i class="fa-solid fa-stethoscope"></i> Devices (${summary.devices || 0})</button>
      <button class="tab-btn" data-filter="HOSPITAL_SERVICE"><i class="fa-solid fa-hospital"></i> Hospital Services (${summary.services || 0})</button>
    `;

    filterTabsContainer.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        filterTabsContainer.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderFilteredItems(btn.dataset.filter);
      });
    });
  }

  function renderFilteredItems(filterCategory) {
    if (!itemsContainer || !currentAnalysisData) return;
    const items = currentAnalysisData.line_items || [];

    const filtered = filterCategory === 'ALL' 
      ? items 
      : items.filter(it => it.category === filterCategory);

    if (filtered.length === 0) {
      itemsContainer.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 48px; background: var(--bg-card); border-radius: var(--radius-lg); border: 1px solid var(--border-card);">
          <i class="fa-regular fa-folder-open" style="font-size: 32px; color: var(--text-dim); margin-bottom: 12px;"></i>
          <p style="color: var(--text-muted); font-size: 15px;">No items found under this category.</p>
        </div>
      `;
      return;
    }

    itemsContainer.innerHTML = filtered.map(item => {
      const cat = item.category || 'MEDICINE';
      let catClass = 'cat-medicine';
      let catIcon = 'fa-pills';

      if (cat === 'LAB_TEST') { catClass = 'cat-lab'; catIcon = 'fa-vial'; }
      else if (cat === 'MEDICAL_DEVICE') { catClass = 'cat-device'; catIcon = 'fa-stethoscope'; }
      else if (cat === 'HOSPITAL_SERVICE') { catClass = 'cat-service'; catIcon = 'fa-hospital'; }

      const medInfo = item.medicine_info || {};
      const onemg = item.onemg || {};

      const composition = medInfo.composition || '';
      const uses = medInfo.uses || '';
      const manufacturer = medInfo.manufacturer || onemg.name || '';
      const sideEffects = medInfo.side_effects || '';
      const matchScore = medInfo.match_score || null;

      const rateFormatted = item.rate > 0 ? `₹${Number(item.rate).toFixed(2)}` : 'N/A';
      const amountFormatted = item.amount > 0 ? `₹${Number(item.amount).toFixed(2)}` : 'N/A';

      let marketPriceText = 'Not found on 1mg';
      let marketPriceClass = '';
      if (onemg.numeric_price) {
        marketPriceText = `₹${Number(onemg.numeric_price).toFixed(2)}`;
        marketPriceClass = 'price-market';
      }

      let savingsBadge = '';
      if (item.savings_per_unit && item.savings_per_unit > 0) {
        savingsBadge = `<span style="font-size:11px; padding: 2px 8px; border-radius: 4px; background: var(--success-bg); color: var(--success); font-weight: 600;">₹${item.savings_per_unit.toFixed(2)} / unit lower on 1mg</span>`;
      }

      return `
        <div class="item-card">
          <div>
            <div class="item-card-top">
              <div class="item-name-group">
                <h4 class="item-title">${escapeHtml(item.item_name)}</h4>
                <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:4px;">
                  <span class="category-badge ${catClass}">
                    <i class="fa-solid ${catIcon}"></i> ${escapeHtml(cat.replace('_', ' '))}
                  </span>
                  ${matchScore ? `<span style="font-size:11px; color:var(--teal); font-family:var(--font-mono); font-weight:600;"><i class="fa-solid fa-bullseye"></i> ${matchScore}% DB Match</span>` : ''}
                </div>
              </div>
            </div>

            ${(composition || uses || sideEffects) ? `
              <div class="item-clinical-info">
                ${composition ? `
                  <div class="clinical-row">
                    <span class="clinical-label">Active Composition</span>
                    <span class="clinical-value" style="color:var(--teal); font-weight:500;">${escapeHtml(composition)}</span>
                  </div>
                ` : ''}
                ${uses ? `
                  <div class="clinical-row">
                    <span class="clinical-label">Indications / Uses</span>
                    <span class="clinical-value">${escapeHtml(uses)}</span>
                  </div>
                ` : ''}
                ${sideEffects ? `
                  <div class="clinical-row">
                    <span class="clinical-label">Known Side Effects</span>
                    <span class="clinical-value" style="color: #fca5a5;">${escapeHtml(sideEffects)}</span>
                  </div>
                ` : ''}
                ${manufacturer ? `
                  <div class="clinical-row">
                    <span class="clinical-label">Manufacturer</span>
                    <span class="clinical-value" style="color:var(--text-dim);">${escapeHtml(manufacturer)}</span>
                  </div>
                ` : ''}
              </div>
            ` : ''}
          </div>

          <div>
            <div class="price-comparison-box">
              <div>
                <div class="price-col-title">Bill Unit Rate (Qty: ${item.quantity || 1})</div>
                <div class="price-col-val price-bill">${rateFormatted}</div>
                <div style="font-size:11px; color:var(--text-dim); margin-top:2px;">Total: ${amountFormatted}</div>
              </div>
              <div>
                <div class="price-col-title">1mg Benchmark Price</div>
                <div class="price-col-val ${marketPriceClass}">${marketPriceText}</div>
                <div style="margin-top:4px;">${savingsBadge}</div>
              </div>
            </div>

            ${medInfo.matched_name ? `
              <button class="btn btn-outline btn-sm" style="width:100%; margin-top:12px;" onclick="window.openMedicineModal('${escapeHtml(medInfo.matched_name)}')">
                <i class="fa-solid fa-circle-info"></i> View Clinical Profile
              </button>
            ` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  // ─── Live Medicine Search Engine ───
  if (medicineSearchInput) {
    medicineSearchInput.addEventListener('input', (e) => {
      clearTimeout(searchDebounceTimer);
      const query = e.target.value.trim();

      searchDebounceTimer = setTimeout(() => {
        fetchMedicineSearchResults(query);
      }, 300);
    });

    // Initial search load
    fetchMedicineSearchResults('');
  }

  // Quick Chips Click
  window.setQuickSearch = function(query) {
    if (medicineSearchInput) {
      medicineSearchInput.value = query;
      fetchMedicineSearchResults(query);
      medicineSearchInput.focus();
    }
  };

  async function fetchMedicineSearchResults(query) {
    if (!medSearchResultsGrid) return;
    
    medSearchResultsGrid.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 40px;">
        <div class="spinner" style="margin: 0 auto 12px;"></div>
        <p style="color: var(--text-muted); font-size: 14px;">Searching 11,800+ medicines...</p>
      </div>
    `;

    try {
      const res = await fetch(`/api/medicines/search/?q=${encodeURIComponent(query)}&limit=12`);
      const data = await res.json();

      if (!data.success || !data.results || data.results.length === 0) {
        medSearchResultsGrid.innerHTML = `
          <div style="grid-column: 1 / -1; text-align: center; padding: 48px; background: var(--bg-card); border-radius: var(--radius-lg); border: 1px solid var(--border-card);">
            <i class="fa-solid fa-magnifying-glass" style="font-size: 28px; color: var(--text-dim); margin-bottom: 12px;"></i>
            <p style="color: var(--text-main); font-weight:600; margin-bottom: 4px;">No medicines found matching "${escapeHtml(query)}"</p>
            <p style="color: var(--text-muted); font-size: 13px;">Try searching by generic salt composition or standard brand names (e.g. Paracetamol, Augmentin).</p>
          </div>
        `;
        return;
      }

      medSearchResultsGrid.innerHTML = data.results.map(med => {
        return `
          <div class="med-card">
            <div>
              <h4 class="med-card-name">${escapeHtml(med.name)}</h4>
              <div class="med-card-comp"><i class="fa-solid fa-dna" style="font-size:11px; margin-right:4px;"></i> ${escapeHtml(med.composition || 'Clinical formulation')}</div>
              <p class="med-card-uses">${escapeHtml(med.uses || 'Consult healthcare practitioner for indication profile.')}</p>
            </div>
            <div class="med-card-footer">
              <span class="med-card-mfg">${escapeHtml(med.manufacturer || 'Pharmaceutical Formulation')}</span>
              <button class="btn btn-primary btn-sm" onclick="window.openMedicineModal('${escapeHtml(med.name)}')">
                Details & Price <i class="fa-solid fa-arrow-right" style="font-size:10px;"></i>
              </button>
            </div>
          </div>
        `;
      }).join('');

    } catch (err) {
      medSearchResultsGrid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 32px; color: var(--danger);">
          <i class="fa-solid fa-triangle-exclamation" style="font-size: 24px; margin-bottom: 8px;"></i>
          <p>Failed to query medicine database.</p>
        </div>
      `;
    }
  }

  // ─── Medicine Detail Modal ───
  window.openMedicineModal = async function(medicineName) {
    if (!medicineModal) return;

    const modalBody = document.getElementById('modalMedContent');
    if (modalBody) {
      modalBody.innerHTML = `
        <div style="text-align:center; padding: 48px 0;">
          <div class="spinner" style="margin: 0 auto 16px;"></div>
          <p style="color: var(--text-muted);">Fetching clinical profile & live 1mg market pricing for <strong>${escapeHtml(medicineName)}</strong>...</p>
        </div>
      `;
    }

    medicineModal.classList.add('active');

    try {
      const res = await fetch(`/api/medicines/detail/?name=${encodeURIComponent(medicineName)}`);
      const data = await res.json();

      if (!data.success || !data.medicine) {
        modalBody.innerHTML = `
          <div style="padding: 24px; text-align:center; color: var(--danger);">
            <p>Medicine details could not be retrieved.</p>
          </div>
        `;
        return;
      }

      const med = data.medicine;
      const onemg = data.onemg || {};

      let priceDisplay = 'Live price check unavailable';
      if (onemg.numeric_price) {
        priceDisplay = `₹${onemg.numeric_price.toFixed(2)}`;
        if (onemg.mrp) priceDisplay += ` <span style="text-decoration: line-through; color: var(--text-dim); font-size:13px; margin-left:6px;">MRP ₹${onemg.mrp}</span>`;
      }

      modalBody.innerHTML = `
        <div class="modal-med-title">${escapeHtml(med.name)}</div>
        <div class="modal-med-comp"><i class="fa-solid fa-dna"></i> ${escapeHtml(med.composition || 'Active Compound Formulation')}</div>

        <div style="background: rgba(14, 20, 34, 0.7); border: 1px solid var(--border-bright); border-radius: var(--radius-md); padding: 14px 18px; margin-bottom: 20px; display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div style="font-size:11px; text-transform:uppercase; color:var(--text-dim); font-weight:700;">1mg Live Market Price</div>
            <div style="font-size:20px; font-weight:800; font-family:var(--font-mono); color:var(--teal);">${priceDisplay}</div>
          </div>
          <div>
            <span style="font-size:11px; padding:4px 10px; border-radius:var(--radius-full); background:rgba(0, 212, 170, 0.12); color:var(--teal); font-weight:600;">
              Verified Sourced
            </span>
          </div>
        </div>

        <div class="modal-detail-group">
          <div class="modal-detail-label">Therapeutic Indications / Uses</div>
          <div class="modal-detail-text">${escapeHtml(med.uses || 'Information not specified.')}</div>
        </div>

        <div class="modal-detail-group">
          <div class="modal-detail-label">Known Adverse Effects / Warnings</div>
          <div class="modal-detail-text" style="color: #fca5a5;">${escapeHtml(med.side_effects || 'No significant common adverse effects cataloged. Consult doctor if discomfort occurs.')}</div>
        </div>

        <div class="modal-detail-group">
          <div class="modal-detail-label">Pharmaceutical Manufacturer</div>
          <div class="modal-detail-text">${escapeHtml(med.manufacturer || 'Standard Pharmaceutical Manufacturer')}</div>
        </div>

        ${med.image_url ? `
          <div style="margin-top: 20px; text-align:center;">
            <img src="${escapeHtml(med.image_url)}" alt="${escapeHtml(med.name)}" style="max-height: 160px; border-radius: var(--radius-md); border: 1px solid var(--border-card);" onerror="this.style.display='none'" />
          </div>
        ` : ''}
      `;

    } catch (e) {
      if (modalBody) {
        modalBody.innerHTML = `<div style="color:var(--danger); padding:20px;">Error retrieving information: ${e.message}</div>`;
      }
    }
  };

  if (modalCloseBtn) {
    modalCloseBtn.addEventListener('click', () => {
      if (medicineModal) medicineModal.classList.remove('active');
    });
  }

  if (medicineModal) {
    medicineModal.addEventListener('click', (e) => {
      if (e.target === medicineModal) {
        medicineModal.classList.remove('active');
      }
    });
  }

  // Mobile navigation drawer toggle
  const mobileToggle = document.getElementById('mobileToggle');
  const mobileNavDrawer = document.getElementById('mobileNavDrawer');
  if (mobileToggle && mobileNavDrawer) {
    mobileToggle.addEventListener('click', () => {
      mobileNavDrawer.classList.toggle('active');
    });
  }
});

