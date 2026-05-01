/**
 * Workflow Confirmation Frontend
 * Handles user interactions for confirming, modifying, or canceling workflow tasks.
 */

class WorkflowUI {
    constructor() {
        this.API_BASE_URL = this.getApiBaseUrl();
        this.workflowId = this.getWorkflowId();
        this.isLoading = false;

        this.elements = {
            modifyInput: document.getElementById('modifyInput'),
            modifyBtn: document.getElementById('modifyBtn'),
            confirmBtn: document.getElementById('confirmBtn'),
            cancelBtn: document.getElementById('cancelBtn'),
            errorMessage: document.getElementById('errorMessage'),
            statusBar: document.getElementById('statusBar'),
            toast: document.getElementById('toast'),
        };

        this.init();
    }

    init() {
        this.bindEvents();
        this.connectWebSocket();
    }

    getApiBaseUrl() {
        const { protocol, hostname } = window.location;
        return `${protocol}//${hostname}:8000`;
    }

    getWorkflowId() {
        const params = new URLSearchParams(window.location.search);
        return params.get('workflowId') || '';
    }

    bindEvents() {
        this.elements.modifyBtn.addEventListener('click', () => this.handleModify());
        this.elements.confirmBtn.addEventListener('click', () => this.handleConfirm());
        this.elements.cancelBtn.addEventListener('click', () => this.handleCancel());

        this.elements.modifyInput.addEventListener('input', () => this.clearError());
        this.elements.modifyInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.ctrlKey) {
                this.handleModify();
            }
        });
    }

    connectWebSocket() {
        if (!this.workflowId) return;

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.hostname}:8000/ws`;

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                this.ws.send(JSON.stringify({
                    type: 'subscribe',
                    workflowId: this.workflowId,
                }));
            };

            this.ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                this.handleWebSocketMessage(msg);
            };

            this.ws.onerror = () => {
                this.showStatus('WebSocket 连接失败，请刷新页面重试', 'error');
            };
        } catch (e) {
            console.error('WebSocket connection failed:', e);
        }
    }

    handleWebSocketMessage(msg) {
        switch (msg.type) {
            case 'confirm_result':
                if (msg.action === 'modify') {
                    this.showToast('修改意见已提交，正在重新生成...', 'success');
                    this.elements.modifyInput.value = '';
                }
                break;
            case 'workflow_completed':
                this.showToast('工作流已完成', 'success');
                this.setLoading(false);
                break;
            case 'workflow_failed':
                this.showToast(`工作流失败: ${msg.error}`, 'error');
                this.setLoading(false);
                break;
            case 'workflow_cancelled':
                this.showToast('工作流已取消', 'success');
                this.setLoading(false);
                break;
        }
    }

    validateInput(value) {
        const trimmed = value.trim();

        if (!trimmed) {
            return { valid: false, message: '请输入需要修改的内容' };
        }

        if (trimmed.length < 2) {
            return { valid: false, message: '修改内容至少需要 2 个字符' };
        }

        if (trimmed.length > 5000) {
            return { valid: false, message: '修改内容不能超过 5000 个字符' };
        }

        const suspiciousPatterns = [
            /<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi,
            /javascript:/gi,
            /on\w+\s*=/gi,
        ];

        for (const pattern of suspiciousPatterns) {
            if (pattern.test(trimmed)) {
                return { valid: false, message: '输入内容包含不安全的字符' };
            }
        }

        return { valid: true, message: '' };
    }

    showError(message) {
        this.elements.modifyInput.classList.add('error');
        this.elements.errorMessage.textContent = message;
        this.elements.errorMessage.classList.add('show');
    }

    clearError() {
        this.elements.modifyInput.classList.remove('error');
        this.elements.errorMessage.classList.remove('show');
        this.elements.errorMessage.textContent = '';
    }

    showStatus(message, type = 'info') {
        this.elements.statusBar.textContent = message;
        this.elements.statusBar.className = `status-bar show ${type}`;
    }

    hideStatus() {
        this.elements.statusBar.classList.remove('show');
    }

    showToast(message, type = 'success') {
        const toast = this.elements.toast;
        toast.textContent = message;
        toast.className = `toast toast-${type}`;

        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        setTimeout(() => {
            toast.classList.remove('show');
        }, 3000);
    }

    setLoading(loading) {
        this.isLoading = loading;
        const btn = this.elements.modifyBtn;
        const textSpan = btn.querySelector('.btn-text');

        if (loading) {
            btn.disabled = true;
            textSpan.textContent = '提交中...';
            const spinner = document.createElement('span');
            spinner.className = 'spinner';
            btn.appendChild(spinner);
        } else {
            btn.disabled = false;
            textSpan.textContent = '修改';
            const spinner = btn.querySelector('.spinner');
            if (spinner) spinner.remove();
        }

        this.elements.confirmBtn.disabled = loading;
        this.elements.cancelBtn.disabled = loading;
    }

    async handleModify() {
        if (this.isLoading) return;

        const feedback = this.elements.modifyInput.value;
        const validation = this.validateInput(feedback);

        if (!validation.valid) {
            this.showError(validation.message);
            this.elements.modifyInput.focus();
            return;
        }

        this.clearError();
        this.setLoading(true);
        this.showStatus('正在提交修改意见...', 'info');

        try {
            const result = await this.submitConfirmation('modify', feedback);
            this.showStatus(result.message, 'success');
            this.showToast('修改意见提交成功', 'success');
            this.elements.modifyInput.value = '';
        } catch (error) {
            const errorMsg = error.message || '提交失败，请稍后重试';
            this.showStatus(errorMsg, 'error');
            this.showToast(errorMsg, 'error');
        } finally {
            this.setLoading(false);
        }
    }

    async handleConfirm() {
        if (this.isLoading) return;

        this.setLoading(true);
        this.showStatus('正在确认...', 'info');

        try {
            const result = await this.submitConfirmation('confirm', '');
            this.showStatus(result.message, 'success');
            this.showToast('已确认，继续执行', 'success');
        } catch (error) {
            const errorMsg = error.message || '确认失败，请稍后重试';
            this.showStatus(errorMsg, 'error');
            this.showToast(errorMsg, 'error');
        } finally {
            this.setLoading(false);
        }
    }

    async handleCancel() {
        if (this.isLoading) return;

        if (!confirm('确定要取消当前任务吗？')) return;

        this.setLoading(true);
        this.showStatus('正在取消任务...', 'info');

        try {
            const result = await this.submitConfirmation('cancel', '');
            this.showStatus(result.message, 'success');
            this.showToast('任务已取消', 'success');
        } catch (error) {
            const errorMsg = error.message || '取消失败，请稍后重试';
            this.showStatus(errorMsg, 'error');
            this.showToast(errorMsg, 'error');
        } finally {
            this.setLoading(false);
        }
    }

    async submitConfirmation(action, feedback) {
        if (!this.workflowId) {
            throw new Error('缺少工作流 ID');
        }

        const url = `${this.API_BASE_URL}/workflows/${encodeURIComponent(this.workflowId)}/confirm`;
        const body = { action, feedback };

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-Request-ID': this.generateRequestId(),
                },
                body: JSON.stringify(body),
                signal: controller.signal,
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const errorMessage = errorData.detail || `请求失败 (${response.status})`;

                if (response.status === 404) {
                    throw new Error('工作流不存在或已过期');
                } else if (response.status === 422) {
                    throw new Error(errorMessage);
                } else if (response.status === 409) {
                    throw new Error('确认提交冲突，请稍后重试');
                } else {
                    throw new Error(errorMessage);
                }
            }

            return await response.json();
        } catch (error) {
            clearTimeout(timeoutId);

            if (error.name === 'AbortError') {
                throw new Error('请求超时，请检查网络连接');
            }

            if (error.name === 'TypeError' && error.message.includes('fetch')) {
                throw new Error('网络连接失败，请检查后端服务是否运行');
            }

            throw error;
        }
    }

    generateRequestId() {
        return `req_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new WorkflowUI();
});
