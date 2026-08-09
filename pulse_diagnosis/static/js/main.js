/**
 * Main JavaScript for Pulse Diagnosis System
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize all components
    initializeTooltips();
    initializeSmoothScroll();
    initializeFormValidation();
});

/**
 * Initialize tooltips for info icons
 */
function initializeTooltips() {
    const tooltipTriggers = document.querySelectorAll('[data-tooltip]');
    tooltipTriggers.forEach(trigger => {
        trigger.addEventListener('mouseenter', showTooltip);
        trigger.addEventListener('mouseleave', hideTooltip);
    });
}

function showTooltip(e) {
    const tooltip = document.createElement('div');
    tooltip.className = 'tooltip';
    tooltip.textContent = e.target.dataset.tooltip;
    document.body.appendChild(tooltip);

    const rect = e.target.getBoundingClientRect();
    tooltip.style.top = rect.bottom + 10 + 'px';
    tooltip.style.left = rect.left + 'px';
}

function hideTooltip() {
    const tooltip = document.querySelector('.tooltip');
    if (tooltip) tooltip.remove();
}

/**
 * Initialize smooth scrolling for anchor links
 */
function initializeSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

/**
 * Initialize form validation
 */
function initializeFormValidation() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const requiredFields = form.querySelectorAll('[required]');
            let isValid = true;

            requiredFields.forEach(field => {
                if (!field.value.trim()) {
                    isValid = false;
                    showFieldError(field, 'This field is required');
                } else {
                    clearFieldError(field);
                }
            });

            if (!isValid) {
                e.preventDefault();
            }
        });
    });
}

function showFieldError(field, message) {
    clearFieldError(field);
    field.classList.add('field-error');
    const error = document.createElement('span');
    error.className = 'error-message';
    error.textContent = message;
    field.parentNode.appendChild(error);
}

function clearFieldError(field) {
    field.classList.remove('field-error');
    const error = field.parentNode.querySelector('.error-message');
    if (error) error.remove();
}

/**
 * API Helper Functions
 */
const API = {
    baseUrl: '/api',

    async analyzePulse(formData) {
        const response = await fetch(`${this.baseUrl}/analyze/`, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': this.getCsrfToken()
            }
        });
        return response.json();
    },

    async getAnalysis(analysisId) {
        const response = await fetch(`${this.baseUrl}/analysis/${analysisId}/`);
        return response.json();
    },

    async getSymptoms() {
        const response = await fetch(`${this.baseUrl}/symptoms/`);
        return response.json();
    },

    getCsrfToken() {
        const cookie = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    }
};

/**
 * Symptom selection helpers
 */
function toggleSymptomCategory(categoryId) {
    const category = document.getElementById(categoryId);
    if (category) {
        category.classList.toggle('collapsed');
    }
}

function selectAllSymptoms(categoryId) {
    const checkboxes = document.querySelectorAll(`#${categoryId} input[type="checkbox"]`);
    checkboxes.forEach(cb => cb.checked = true);
}

function clearAllSymptoms(categoryId) {
    const checkboxes = document.querySelectorAll(`#${categoryId} input[type="checkbox"]`);
    checkboxes.forEach(cb => cb.checked = false);
}

/**
 * Video preview functionality
 */
function previewVideo(input) {
    const preview = document.getElementById('videoPreview');
    if (input.files && input.files[0] && preview) {
        const reader = new FileReader();
        reader.onload = function(e) {
            preview.src = e.target.result;
            preview.style.display = 'block';
        };
        reader.readAsDataURL(input.files[0]);
    }
}

/**
 * Copy to clipboard utility
 */
function copyToClipboard(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;

    const text = element.textContent;
    navigator.clipboard.writeText(text).then(() => {
        showNotification('Copied to clipboard!', 'success');
    }).catch(err => {
        console.error('Failed to copy:', err);
        showNotification('Failed to copy', 'error');
    });
}

/**
 * Show notification toast
 */
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);

    setTimeout(() => {
        notification.classList.add('show');
    }, 100);

    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

/**
 * Format file size
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Validate video file
 */
function validateVideoFile(file) {
    const maxSize = 100 * 1024 * 1024; // 100 MB
    const allowedTypes = ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/webm'];

    if (file.size > maxSize) {
        return { valid: false, error: 'File size exceeds 100 MB limit' };
    }

    if (!allowedTypes.includes(file.type)) {
        return { valid: false, error: 'Invalid file type. Please upload MP4, MOV, AVI, or WebM' };
    }

    return { valid: true };
}
