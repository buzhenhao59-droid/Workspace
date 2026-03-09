/**
 * 拓岳电商系统 - API服务
 * 前端与后端通信的核心模块
 */

const API_BASE_URL = 'http://localhost:3000/api';

// API请求封装
class ApiService {
    constructor() {
        this.token = localStorage.getItem('token');
    }

    // 设置Token
    setToken(token) {
        this.token = token;
        localStorage.setItem('token', token);
    }

    // 清除Token
    clearToken() {
        this.token = null;
        localStorage.removeItem('token');
    }

    // 通用请求方法
    async request(endpoint, options = {}) {
        const url = `${API_BASE_URL}${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };

        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }

        try {
            const response = await fetch(url, {
                ...options,
                headers
            });

            const data = await response.json();

            if (!response.ok) {
                if (response.status === 401) {
                    // Token过期，跳转登录
                    this.clearToken();
                    window.dispatchEvent(new CustomEvent('auth:logout'));
                }
                throw new Error(data.message || '请求失败');
            }

            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    // GET请求
    get(endpoint, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const url = queryString ? `${endpoint}?${queryString}` : endpoint;
        return this.request(url, { method: 'GET' });
    }

    // POST请求
    post(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    // PUT请求
    put(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    // DELETE请求
    delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }

    // ==================== 认证接口 ====================
    
    async login(username, password) {
        const result = await this.post('/auth/login', { username, password });
        if (result.success && result.data.token) {
            this.setToken(result.data.token);
        }
        return result;
    }

    async register(userData) {
        return this.post('/auth/register', userData);
    }

    async getProfile() {
        return this.get('/auth/profile');
    }

    // ==================== 销售管理接口 ====================

    // 订单
    async getOrders(params = {}) {
        return this.get('/sales/orders', params);
    }

    async getOrder(id) {
        return this.get(`/sales/orders/${id}`);
    }

    async createOrder(orderData) {
        return this.post('/sales/orders', orderData);
    }

    async auditOrder(id) {
        return this.post(`/sales/orders/${id}/audit`);
    }

    async splitOrder(id, splits) {
        return this.post(`/sales/orders/${id}/split`, { splits });
    }

    async mergeOrders(orderIds) {
        return this.post('/sales/orders/merge', { orderIds });
    }

    async markOrderException(id, reason, description) {
        return this.post(`/sales/orders/${id}/mark-exception`, { reason, description });
    }

    // Listing
    async getListings(params = {}) {
        return this.get('/sales/listings', params);
    }

    async getListing(id) {
        return this.get(`/sales/listings/${id}`);
    }

    async updateListingPrice(id, price, reason) {
        return this.put(`/sales/listings/${id}/price`, { price, reason });
    }

    async publishListing(id, platforms) {
        return this.post(`/sales/listings/${id}/publish`, { platforms });
    }

    async getAplusContent(id) {
        return this.get(`/sales/listings/${id}/aplus`);
    }

    async updateAplusContent(id, content) {
        return this.put(`/sales/listings/${id}/aplus`, content);
    }

    // 售后
    async getAftersales(params = {}) {
        return this.get('/sales/aftersales', params);
    }

    async processAftersale(id, action, refundAmount, notes) {
        return this.post(`/sales/aftersales/${id}/process`, { action, refundAmount, notes });
    }

    async getAftersalesAnalytics(params = {}) {
        return this.get('/sales/aftersales/analytics', params);
    }

    // ==================== 产品与库存接口 ====================

    // 产品
    async getProducts(params = {}) {
        return this.get('/products', params);
    }

    async getProduct(id) {
        return this.get(`/products/${id}`);
    }

    async createProduct(productData) {
        return this.post('/products', productData);
    }

    async updateProduct(id, productData) {
        return this.put(`/products/${id}`, productData);
    }

    async linkSource(id, sourceData) {
        return this.post(`/products/${id}/link-source`, sourceData);
    }

    // 库存
    async getInventory(params = {}) {
        return this.get('/inventory', params);
    }

    async getInventorySummary() {
        return this.get('/inventory/summary');
    }

    async createTransaction(transactionData) {
        return this.post('/inventory/transactions', transactionData);
    }

    async getTransactions(params = {}) {
        return this.get('/inventory/transactions', params);
    }

    // ==================== FBA接口 ====================

    async getReplenishmentSuggestions() {
        return this.get('/fba/replenishment/suggestions');
    }

    async calculateReplenishment(data) {
        return this.post('/fba/replenishment/calculate', data);
    }

    async getFbaShipments(params = {}) {
        return this.get('/fba/shipments', params);
    }

    async createFbaShipment(shipmentData) {
        return this.post('/fba/shipments', shipmentData);
    }

    async updateFbaShipment(id, shipmentData) {
        return this.put(`/fba/shipments/${id}`, shipmentData);
    }

    async createBoxing(id, boxes) {
        return this.post(`/fba/shipments/${id}/boxing`, { boxes });
    }

    async syncTracking(id, trackingNumber, carrier) {
        return this.post(`/fba/shipments/${id}/tracking`, { trackingNumber, carrier });
    }

    // ==================== 物流接口 ====================

    async getLogisticsChannels() {
        return this.get('/logistics/channels');
    }

    async calculateFreight(data) {
        return this.post('/logistics/calculate-freight', data);
    }

    async printLabel(channelId, shipmentId) {
        return this.post('/logistics/print-label', { channelId, shipmentId });
    }

    async getTracking(trackingNumber) {
        return this.get(`/logistics/tracking/${trackingNumber}`);
    }

    // ==================== 采购接口 ====================

    async getPurchases(params = {}) {
        return this.get('/purchases', params);
    }

    async createPurchase(purchaseData) {
        return this.post('/purchases', purchaseData);
    }

    async updatePurchaseStage(id, stage, status, notes, issues) {
        return this.put(`/purchases/${id}/stage/${stage}`, { status, notes, issues });
    }

    // ==================== 财务接口 ====================

    async getProfitReport(params = {}) {
        return this.get('/finance/profit-report', params);
    }

    async getProfitSummary(params = {}) {
        return this.get('/finance/profit-summary', params);
    }

    async getAccountsPayable(params = {}) {
        return this.get('/finance/accounts-payable', params);
    }

    async getPlatformRevenue(params = {}) {
        return this.get('/finance/platform-revenue', params);
    }

    async getExpenses(params = {}) {
        return this.get('/finance/expenses', params);
    }

    async approveExpense(id) {
        return this.post(`/finance/expenses/${id}/approve`);
    }

    // ==================== AI接口 ====================

    async generateDescription(sku, features, language) {
        return this.post('/ai/generate-description', { sku, features, language });
    }

    async translate(text, sourceLang, targetLang) {
        return this.post('/ai/translate', { text, sourceLang, targetLang });
    }

    async analyzeReviews(sku, reviews) {
        return this.post('/ai/analyze-reviews', { sku, reviews });
    }

    // ==================== 文件上传 ====================

    async uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`${API_BASE_URL}/upload`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${this.token}`
            },
            body: formData
        });

        return response.json();
    }
}

// 导出单例
const api = new ApiService();
export default api;

// 如果不使用模块化，挂载到window
if (typeof window !== 'undefined') {
    window.api = api;
}
