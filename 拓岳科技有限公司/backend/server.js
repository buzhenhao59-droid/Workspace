const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const jwt = require('jsonwebtoken');
const multer = require('multer');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;
const JWT_SECRET = 'tuoyue-ecommerce-secret-key-2026';

// 中间件
app.use(cors());
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));
app.use('/uploads', express.static(path.join(__dirname, 'uploads')));

// 确保数据目录存在
const dataDir = path.join(__dirname, 'data');
const uploadDir = path.join(__dirname, 'uploads');
if (!fs.existsSync(dataDir)) fs.mkdirSync(dataDir, { recursive: true });
if (!fs.existsSync(uploadDir)) fs.mkdirSync(uploadDir, { recursive: true });

// 数据存储
const db = {
    users: require('./data/users'),
    orders: require('./data/orders'),
    listings: require('./data/listings'),
    aftersales: require('./data/aftersales'),
    products: require('./data/products'),
    warehouses: require('./data/warehouses'),
    inventory: require('./data/inventory'),
    fbaShipments: require('./data/fbaShipments'),
    replenishment: require('./data/replenishment'),
    logistics: require('./data/logistics'),
    purchases: require('./data/purchases'),
    finance: require('./data/finance'),
    accounts: require('./data/accounts')
};

// JWT 验证中间件
const authMiddleware = (req, res, next) => {
    const token = req.headers.authorization?.replace('Bearer ', '');
    if (!token) {
        return res.status(401).json({ success: false, message: '未提供认证令牌' });
    }
    try {
        const decoded = jwt.verify(token, JWT_SECRET);
        req.user = decoded;
        next();
    } catch (error) {
        return res.status(401).json({ success: false, message: '令牌无效或已过期' });
    }
};

// ==================== 认证接口 ====================
app.post('/api/auth/login', (req, res) => {
    const { username, password } = req.body;
    const user = db.users.find(u => u.username === username && u.password === password);
    
    if (!user) {
        return res.status(401).json({ success: false, message: '用户名或密码错误' });
    }
    
    const token = jwt.sign(
        { id: user.id, username: user.username, role: user.role },
        JWT_SECRET,
        { expiresIn: '24h' }
    );
    
    res.json({
        success: true,
        data: {
            token,
            user: { id: user.id, username: user.username, name: user.name, role: user.role }
        }
    });
});

app.post('/api/auth/register', (req, res) => {
    const { username, password, name, email } = req.body;
    
    if (db.users.find(u => u.username === username)) {
        return res.status(400).json({ success: false, message: '用户名已存在' });
    }
    
    const newUser = {
        id: `user_${Date.now()}`,
        username,
        password, // 生产环境应加密
        name,
        email,
        role: 'user',
        createdAt: new Date().toISOString()
    };
    
    db.users.push(newUser);
    saveData('users');
    
    res.json({ success: true, message: '注册成功' });
});

app.get('/api/auth/profile', authMiddleware, (req, res) => {
    const user = db.users.find(u => u.id === req.user.id);
    if (!user) {
        return res.status(404).json({ success: false, message: '用户不存在' });
    }
    res.json({
        success: true,
        data: { id: user.id, username: user.username, name: user.name, email: user.email, role: user.role }
    });
});

// ==================== 销售管理接口 ====================

// 订单中心
app.get('/api/sales/orders', authMiddleware, (req, res) => {
    const { status, platform, page = 1, limit = 20 } = req.query;
    let orders = [...db.orders];
    
    if (status) orders = orders.filter(o => o.status === status);
    if (platform) orders = orders.filter(o => o.platform === platform);
    
    const total = orders.length;
    const start = (page - 1) * limit;
    const data = orders.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.get('/api/sales/orders/:id', authMiddleware, (req, res) => {
    const order = db.orders.find(o => o.id === req.params.id);
    if (!order) {
        return res.status(404).json({ success: false, message: '订单不存在' });
    }
    res.json({ success: true, data: order });
});

app.post('/api/sales/orders', authMiddleware, (req, res) => {
    const newOrder = {
        id: `ORD_${Date.now()}`,
        ...req.body,
        status: 'pending',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
    };
    db.orders.push(newOrder);
    saveData('orders');
    res.json({ success: true, data: newOrder, message: '订单创建成功' });
});

app.put('/api/sales/orders/:id', authMiddleware, (req, res) => {
    const index = db.orders.findIndex(o => o.id === req.params.id);
    if (index === -1) {
        return res.status(404).json({ success: false, message: '订单不存在' });
    }
    db.orders[index] = {
        ...db.orders[index],
        ...req.body,
        updatedAt: new Date().toISOString()
    };
    saveData('orders');
    res.json({ success: true, data: db.orders[index], message: '订单更新成功' });
});

// 订单审核
app.post('/api/sales/orders/:id/audit', authMiddleware, (req, res) => {
    const order = db.orders.find(o => o.id === req.params.id);
    if (!order) {
        return res.status(404).json({ success: false, message: '订单不存在' });
    }
    order.status = 'audited';
    order.auditedAt = new Date().toISOString();
    order.auditedBy = req.user.id;
    saveData('orders');
    res.json({ success: true, data: order, message: '订单审核成功' });
});

// 订单拆分
app.post('/api/sales/orders/:id/split', authMiddleware, (req, res) => {
    const { splits } = req.body; // [{ items: [...], warehouse: 'xxx' }, ...]
    const originalOrder = db.orders.find(o => o.id === req.params.id);
    if (!originalOrder) {
        return res.status(404).json({ success: false, message: '订单不存在' });
    }
    
    const newOrders = splits.map((split, index) => ({
        id: `ORD_${Date.now()}_${index}`,
        ...originalOrder,
        items: split.items,
        warehouse: split.warehouse,
        parentOrderId: originalOrder.id,
        status: 'pending',
        createdAt: new Date().toISOString()
    }));
    
    originalOrder.status = 'split';
    originalOrder.splitOrders = newOrders.map(o => o.id);
    db.orders.push(...newOrders);
    saveData('orders');
    
    res.json({ success: true, data: { original: originalOrder, newOrders }, message: '订单拆分成功' });
});

// 订单合并
app.post('/api/sales/orders/merge', authMiddleware, (req, res) => {
    const { orderIds } = req.body;
    const ordersToMerge = db.orders.filter(o => orderIds.includes(o.id));
    
    if (ordersToMerge.length < 2) {
        return res.status(400).json({ success: false, message: '至少需要2个订单才能合并' });
    }
    
    const mergedOrder = {
        id: `ORD_${Date.now()}`,
        items: ordersToMerge.flatMap(o => o.items),
        mergedFrom: orderIds,
        status: 'pending',
        createdAt: new Date().toISOString()
    };
    
    ordersToMerge.forEach(o => o.status = 'merged');
    db.orders.push(mergedOrder);
    saveData('orders');
    
    res.json({ success: true, data: mergedOrder, message: '订单合并成功' });
});

// 异常订单标记
app.post('/api/sales/orders/:id/mark-exception', authMiddleware, (req, res) => {
    const { reason, description } = req.body;
    const order = db.orders.find(o => o.id === req.params.id);
    if (!order) {
        return res.status(404).json({ success: false, message: '订单不存在' });
    }
    
    order.status = 'exception';
    order.exception = { reason, description, markedAt: new Date().toISOString(), markedBy: req.user.id };
    saveData('orders');
    res.json({ success: true, data: order, message: '已标记为异常订单' });
});

// Listing管理
app.get('/api/sales/listings', authMiddleware, (req, res) => {
    const { status, shop, page = 1, limit = 20 } = req.query;
    let listings = [...db.listings];
    
    if (status) listings = listings.filter(l => l.status === status);
    if (shop) listings = listings.filter(l => l.shop === shop);
    
    const total = listings.length;
    const start = (page - 1) * limit;
    const data = listings.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.get('/api/sales/listings/:id', authMiddleware, (req, res) => {
    const listing = db.listings.find(l => l.id === req.params.id);
    if (!listing) {
        return res.status(404).json({ success: false, message: 'Listing不存在' });
    }
    res.json({ success: true, data: listing });
});

// 调价
app.put('/api/sales/listings/:id/price', authMiddleware, (req, res) => {
    const { price, reason } = req.body;
    const listing = db.listings.find(l => l.id === req.params.id);
    if (!listing) {
        return res.status(404).json({ success: false, message: 'Listing不存在' });
    }
    
    listing.priceHistory = listing.priceHistory || [];
    listing.priceHistory.push({ oldPrice: listing.price, newPrice: price, reason, changedAt: new Date().toISOString() });
    listing.price = price;
    listing.updatedAt = new Date().toISOString();
    saveData('listings');
    
    res.json({ success: true, data: listing, message: '调价成功' });
});

// 刊登
app.post('/api/sales/listings/:id/publish', authMiddleware, (req, res) => {
    const { platforms } = req.body;
    const listing = db.listings.find(l => l.id === req.params.id);
    if (!listing) {
        return res.status(404).json({ success: false, message: 'Listing不存在' });
    }
    
    listing.publishedPlatforms = [...new Set([...(listing.publishedPlatforms || []), ...platforms])];
    listing.status = 'online';
    listing.publishedAt = new Date().toISOString();
    saveData('listings');
    
    res.json({ success: true, data: listing, message: '刊登成功' });
});

// A+页面管理
app.get('/api/sales/listings/:id/aplus', authMiddleware, (req, res) => {
    const listing = db.listings.find(l => l.id === req.params.id);
    if (!listing) {
        return res.status(404).json({ success: false, message: 'Listing不存在' });
    }
    res.json({ success: true, data: listing.aplusContent || null });
});

app.put('/api/sales/listings/:id/aplus', authMiddleware, (req, res) => {
    const listing = db.listings.find(l => l.id === req.params.id);
    if (!listing) {
        return res.status(404).json({ success: false, message: 'Listing不存在' });
    }
    
    listing.aplusContent = {
        ...req.body,
        updatedAt: new Date().toISOString(),
        updatedBy: req.user.id
    };
    saveData('listings');
    
    res.json({ success: true, data: listing, message: 'A+页面更新成功' });
});

// 售后中心
app.get('/api/sales/aftersales', authMiddleware, (req, res) => {
    const { status, type, page = 1, limit = 20 } = req.query;
    let aftersales = [...db.aftersales];
    
    if (status) aftersales = aftersales.filter(a => a.status === status);
    if (type) aftersales = aftersales.filter(a => a.type === type);
    
    const total = aftersales.length;
    const start = (page - 1) * limit;
    const data = aftersales.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.post('/api/sales/aftersales/:id/process', authMiddleware, (req, res) => {
    const { action, refundAmount, notes } = req.body;
    const aftersale = db.aftersales.find(a => a.id === req.params.id);
    if (!aftersale) {
        return res.status(404).json({ success: false, message: '售后工单不存在' });
    }
    
    aftersale.status = action === 'approve' ? 'completed' : 'rejected';
    aftersale.refundAmount = refundAmount;
    aftersale.processNotes = notes;
    aftersale.processedAt = new Date().toISOString();
    aftersale.processedBy = req.user.id;
    saveData('aftersales');
    
    res.json({ success: true, data: aftersale, message: '处理成功' });
});

// 退货数据分析
app.get('/api/sales/aftersales/analytics', authMiddleware, (req, res) => {
    const { startDate, endDate } = req.query;
    let aftersales = [...db.aftersales];
    
    if (startDate) aftersales = aftersales.filter(a => a.createdAt >= startDate);
    if (endDate) aftersales = aftersales.filter(a => a.createdAt <= endDate);
    
    const analytics = {
        total: aftersales.length,
        byType: {},
        byReason: {},
        byStatus: {},
        totalRefundAmount: 0
    };
    
    aftersales.forEach(a => {
        analytics.byType[a.type] = (analytics.byType[a.type] || 0) + 1;
        analytics.byReason[a.reason] = (analytics.byReason[a.reason] || 0) + 1;
        analytics.byStatus[a.status] = (analytics.byStatus[a.status] || 0) + 1;
        analytics.totalRefundAmount += a.refundAmount || 0;
    });
    
    res.json({ success: true, data: analytics });
});

// ==================== 产品与库存管理接口 ====================

// 产品库
app.get('/api/products', authMiddleware, (req, res) => {
    const { category, brand, page = 1, limit = 20 } = req.query;
    let products = [...db.products];
    
    if (category) products = products.filter(p => p.category === category);
    if (brand) products = products.filter(p => p.brand === brand);
    
    const total = products.length;
    const start = (page - 1) * limit;
    const data = products.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.get('/api/products/:id', authMiddleware, (req, res) => {
    const product = db.products.find(p => p.id === req.params.id);
    if (!product) {
        return res.status(404).json({ success: false, message: '产品不存在' });
    }
    res.json({ success: true, data: product });
});

app.post('/api/products', authMiddleware, (req, res) => {
    const newProduct = {
        id: `PROD_${Date.now()}`,
        ...req.body,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
    };
    db.products.push(newProduct);
    saveData('products');
    res.json({ success: true, data: newProduct, message: '产品创建成功' });
});

app.put('/api/products/:id', authMiddleware, (req, res) => {
    const index = db.products.findIndex(p => p.id === req.params.id);
    if (index === -1) {
        return res.status(404).json({ success: false, message: '产品不存在' });
    }
    db.products[index] = {
        ...db.products[index],
        ...req.body,
        updatedAt: new Date().toISOString()
    };
    saveData('products');
    res.json({ success: true, data: db.products[index], message: '产品更新成功' });
});

// 货源配对
app.post('/api/products/:id/link-source', authMiddleware, (req, res) => {
    const { sourceType, sourceUrl, sourceSku, sourcePrice } = req.body;
    const product = db.products.find(p => p.id === req.params.id);
    if (!product) {
        return res.status(404).json({ success: false, message: '产品不存在' });
    }
    
    product.sourceLinks = product.sourceLinks || [];
    product.sourceLinks.push({
        sourceType, // 1688, alibaba, etc.
        sourceUrl,
        sourceSku,
        sourcePrice,
        linkedAt: new Date().toISOString()
    });
    saveData('products');
    
    res.json({ success: true, data: product, message: '货源配对成功' });
});

// 多仓库存管理
app.get('/api/inventory', authMiddleware, (req, res) => {
    const { warehouse, sku, page = 1, limit = 20 } = req.query;
    let inventory = [...db.inventory];
    
    if (warehouse) inventory = inventory.filter(i => i.warehouseId === warehouse);
    if (sku) inventory = inventory.filter(i => i.sku.includes(sku));
    
    const total = inventory.length;
    const start = (page - 1) * limit;
    const data = inventory.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.get('/api/inventory/summary', authMiddleware, (req, res) => {
    const warehouses = db.warehouses.map(w => {
        const warehouseInventory = db.inventory.filter(i => i.warehouseId === w.id);
        return {
            ...w,
            totalSku: warehouseInventory.length,
            totalQuantity: warehouseInventory.reduce((sum, i) => sum + i.quantity, 0),
            pendingOut: warehouseInventory.reduce((sum, i) => sum + (i.pendingOut || 0), 0),
            inTransit: warehouseInventory.reduce((sum, i) => sum + (i.inTransit || 0), 0)
        };
    });
    
    res.json({ success: true, data: warehouses });
});

// 进出库流转
app.get('/api/inventory/transactions', authMiddleware, (req, res) => {
    const { type, warehouse, page = 1, limit = 20 } = req.query;
    let transactions = db.inventory.flatMap(i => i.transactions || []);
    
    if (type) transactions = transactions.filter(t => t.type === type);
    if (warehouse) transactions = transactions.filter(t => t.warehouseId === warehouse);
    
    transactions.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    
    const total = transactions.length;
    const start = (page - 1) * limit;
    const data = transactions.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.post('/api/inventory/transactions', authMiddleware, (req, res) => {
    const { type, warehouseId, items, notes } = req.body;
    const transaction = {
        id: `TXN_${Date.now()}`,
        type, // inbound, outbound, transfer, check
        warehouseId,
        items,
        notes,
        status: 'pending',
        createdAt: new Date().toISOString(),
        createdBy: req.user.id
    };
    
    // 更新库存
    items.forEach(item => {
        const inventory = db.inventory.find(i => i.warehouseId === warehouseId && i.sku === item.sku);
        if (inventory) {
            if (type === 'inbound') inventory.quantity += item.quantity;
            else if (type === 'outbound') inventory.quantity -= item.quantity;
            
            inventory.transactions = inventory.transactions || [];
            inventory.transactions.push(transaction);
        }
    });
    
    saveData('inventory');
    res.json({ success: true, data: transaction, message: '出入库单创建成功' });
});

// ==================== FBA仓储与补货接口 ====================

// 智能补货建议
app.get('/api/fba/replenishment/suggestions', authMiddleware, (req, res) => {
    const suggestions = db.replenishment.map(r => {
        const inventory = db.inventory.find(i => i.sku === r.sku && i.warehouseId === 'fba');
        return {
            ...r,
            currentStock: inventory?.quantity || 0,
            urgency: r.suggestedQuantity > 200 ? 'urgent' : r.suggestedQuantity > 100 ? 'medium' : 'normal'
        };
    });
    
    res.json({ success: true, data: suggestions });
});

app.post('/api/fba/replenishment/calculate', authMiddleware, (req, res) => {
    const { sku, averageDailySales, leadTime, safetyDays = 7 } = req.body;
    
    const inventory = db.inventory.find(i => i.sku === sku && i.warehouseId === 'fba');
    const currentStock = inventory?.quantity || 0;
    
    // 补货计算公式
    const reorderPoint = averageDailySales * (leadTime + safetyDays);
    const suggestedQuantity = Math.max(0, Math.ceil((reorderPoint - currentStock) * 1.2));
    
    const result = {
        sku,
        currentStock,
        averageDailySales,
        leadTime,
        reorderPoint,
        suggestedQuantity,
        urgency: suggestedQuantity > 200 ? 'urgent' : suggestedQuantity > 100 ? 'medium' : 'normal',
        calculatedAt: new Date().toISOString()
    };
    
    res.json({ success: true, data: result });
});

// 货件管理
app.get('/api/fba/shipments', authMiddleware, (req, res) => {
    const { status, page = 1, limit = 20 } = req.query;
    let shipments = [...db.fbaShipments];
    
    if (status) shipments = shipments.filter(s => s.status === status);
    
    const total = shipments.length;
    const start = (page - 1) * limit;
    const data = shipments.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.post('/api/fba/shipments', authMiddleware, (req, res) => {
    const shipment = {
        id: `FBA_${Date.now()}`,
        ...req.body,
        status: 'draft',
        createdAt: new Date().toISOString(),
        createdBy: req.user.id
    };
    db.fbaShipments.push(shipment);
    saveData('fbaShipments');
    res.json({ success: true, data: shipment, message: '发货计划创建成功' });
});

app.put('/api/fba/shipments/:id', authMiddleware, (req, res) => {
    const index = db.fbaShipments.findIndex(s => s.id === req.params.id);
    if (index === -1) {
        return res.status(404).json({ success: false, message: '货件不存在' });
    }
    db.fbaShipments[index] = {
        ...db.fbaShipments[index],
        ...req.body,
        updatedAt: new Date().toISOString()
    };
    saveData('fbaShipments');
    res.json({ success: true, data: db.fbaShipments[index], message: '货件更新成功' });
});

// 装箱任务
app.post('/api/fba/shipments/:id/boxing', authMiddleware, (req, res) => {
    const { boxes } = req.body; // [{ items: [...], weight, dimensions }, ...]
    const shipment = db.fbaShipments.find(s => s.id === req.params.id);
    if (!shipment) {
        return res.status(404).json({ success: false, message: '货件不存在' });
    }
    
    shipment.boxes = boxes.map((box, index) => ({
        id: `BOX_${Date.now()}_${index}`,
        ...box,
        packedAt: new Date().toISOString()
    }));
    shipment.status = 'packed';
    saveData('fbaShipments');
    
    res.json({ success: true, data: shipment, message: '装箱任务创建成功' });
});

// 跟踪号同步
app.post('/api/fba/shipments/:id/tracking', authMiddleware, (req, res) => {
    const { trackingNumber, carrier } = req.body;
    const shipment = db.fbaShipments.find(s => s.id === req.params.id);
    if (!shipment) {
        return res.status(404).json({ success: false, message: '货件不存在' });
    }
    
    shipment.trackingNumber = trackingNumber;
    shipment.carrier = carrier;
    shipment.status = 'shipped';
    shipment.shippedAt = new Date().toISOString();
    saveData('fbaShipments');
    
    res.json({ success: true, data: shipment, message: '跟踪号同步成功' });
});

// ==================== 物流与供应链管理接口 ====================

// 物流渠道管理
app.get('/api/logistics/channels', authMiddleware, (req, res) => {
    res.json({ success: true, data: db.logistics.channels });
});

// 运费试算
app.post('/api/logistics/calculate-freight', authMiddleware, (req, res) => {
    const { channelId, weight, dimensions, destination } = req.body;
    const channel = db.logistics.channels.find(c => c.id === channelId);
    
    if (!channel) {
        return res.status(404).json({ success: false, message: '物流渠道不存在' });
    }
    
    // 简单的运费计算（实际应调用物流商API）
    const baseRate = channel.baseRate;
    const volumeWeight = (dimensions.length * dimensions.width * dimensions.height) / 5000;
    const chargeableWeight = Math.max(weight, volumeWeight);
    const freight = baseRate * chargeableWeight;
    
    res.json({
        success: true,
        data: {
            channelId,
            channelName: channel.name,
            weight,
            volumeWeight,
            chargeableWeight,
            freight: freight.toFixed(2),
            estimatedDays: channel.estimatedDays,
            currency: channel.currency
        }
    });
});

// 面单打印
app.post('/api/logistics/print-label', authMiddleware, (req, res) => {
    const { channelId, shipmentId } = req.body;
    
    // 模拟面单生成
    const labelUrl = `/uploads/labels/${shipmentId}_${Date.now()}.pdf`;
    
    res.json({
        success: true,
        data: {
            labelUrl,
            shipmentId,
            printedAt: new Date().toISOString()
        },
        message: '面单生成成功'
    });
});

// 物流轨迹查询
app.get('/api/logistics/tracking/:trackingNumber', authMiddleware, (req, res) => {
    const { trackingNumber } = req.params;
    
    // 模拟轨迹数据
    const tracking = {
        trackingNumber,
        carrier: 'DHL',
        status: 'in_transit',
        estimatedDelivery: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString(),
        events: [
            { time: '2026-03-03 10:00', location: '深圳', status: '已揽收', coordinates: [114.0645, 22.6125] },
            { time: '2026-03-03 14:30', location: '香港转运中心', status: '转运中', coordinates: [114.1694, 22.3193] },
            { time: '2026-03-04 08:00', location: '美国洛杉矶', status: '清关中', coordinates: [-118.2437, 34.0522] },
            { time: '2026-03-04 16:00', location: '美国洛杉矶', status: '派送中', coordinates: [-118.2437, 34.0522] }
        ]
    };
    
    res.json({ success: true, data: tracking });
});

// 采购管理
app.get('/api/purchases', authMiddleware, (req, res) => {
    const { status, supplier, page = 1, limit = 20 } = req.query;
    let purchases = [...db.purchases];
    
    if (status) purchases = purchases.filter(p => p.status === status);
    if (supplier) purchases = purchases.filter(p => p.supplierId === supplier);
    
    const total = purchases.length;
    const start = (page - 1) * limit;
    const data = purchases.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.post('/api/purchases', authMiddleware, (req, res) => {
    const purchase = {
        id: `PO_${Date.now()}`,
        ...req.body,
        status: 'pending',
        stages: {
            inbound: { status: 'pending', completedAt: null },
            qualityCheck: { status: 'pending', completedAt: null },
            reconciliation: { status: 'pending', completedAt: null, issues: [] }
        },
        createdAt: new Date().toISOString(),
        createdBy: req.user.id
    };
    db.purchases.push(purchase);
    saveData('purchases');
    res.json({ success: true, data: purchase, message: '采购单创建成功' });
});

// 采购流程阶段更新
app.put('/api/purchases/:id/stage/:stage', authMiddleware, (req, res) => {
    const { stage } = req.params;
    const { status, notes, issues } = req.body;
    const purchase = db.purchases.find(p => p.id === req.params.id);
    
    if (!purchase) {
        return res.status(404).json({ success: false, message: '采购单不存在' });
    }
    
    if (!purchase.stages[stage]) {
        return res.status(400).json({ success: false, message: '无效的阶段' });
    }
    
    purchase.stages[stage].status = status;
    purchase.stages[stage].completedAt = status === 'completed' ? new Date().toISOString() : null;
    if (notes) purchase.stages[stage].notes = notes;
    if (issues) purchase.stages[stage].issues = issues;
    
    // 检查是否所有阶段完成
    const allCompleted = Object.values(purchase.stages).every(s => s.status === 'completed');
    if (allCompleted) purchase.status = 'completed';
    
    saveData('purchases');
    res.json({ success: true, data: purchase, message: '阶段状态更新成功' });
});

// ==================== 财务与报表管理接口 ====================

// 精细化利润核算
app.get('/api/finance/profit-report', authMiddleware, (req, res) => {
    const { startDate, endDate, sku } = req.query;
    let report = [...db.finance.profitReport];
    
    if (startDate) report = report.filter(r => r.date >= startDate);
    if (endDate) report = report.filter(r => r.date <= endDate);
    if (sku) report = report.filter(r => r.sku === sku);
    
    res.json({ success: true, data: report });
});

app.get('/api/finance/profit-summary', authMiddleware, (req, res) => {
    const { startDate, endDate } = req.query;
    let reports = [...db.finance.profitReport];
    
    if (startDate) reports = reports.filter(r => r.date >= startDate);
    if (endDate) reports = reports.filter(r => r.date <= endDate);
    
    const summary = {
        totalSales: reports.reduce((sum, r) => sum + r.sales, 0),
        totalCost: reports.reduce((sum, r) => sum + r.cost, 0),
        totalCommission: reports.reduce((sum, r) => sum + r.commission, 0),
        totalAdSpend: reports.reduce((sum, r) => sum + r.adSpend, 0),
        totalLogistics: reports.reduce((sum, r) => sum + r.logistics, 0),
        totalProfit: reports.reduce((sum, r) => sum + r.profit, 0),
        averageProfitMargin: 0
    };
    
    summary.averageProfitMargin = summary.totalSales > 0 
        ? ((summary.totalProfit / summary.totalSales) * 100).toFixed(2) 
        : 0;
    
    res.json({ success: true, data: summary });
});

// 往来账款管理
app.get('/api/finance/accounts-payable', authMiddleware, (req, res) => {
    const { status, supplier, page = 1, limit = 20 } = req.query;
    let accounts = [...db.accounts.payable];
    
    if (status) accounts = accounts.filter(a => a.status === status);
    if (supplier) accounts = accounts.filter(a => a.supplierId === supplier);
    
    const total = accounts.length;
    const start = (page - 1) * limit;
    const data = accounts.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.get('/api/finance/platform-revenue', authMiddleware, (req, res) => {
    const { status, platform, page = 1, limit = 20 } = req.query;
    let revenue = [...db.accounts.platformRevenue];
    
    if (status) revenue = revenue.filter(r => r.status === status);
    if (platform) revenue = revenue.filter(r => r.platform === platform);
    
    const total = revenue.length;
    const start = (page - 1) * limit;
    const data = revenue.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.get('/api/finance/expenses', authMiddleware, (req, res) => {
    const { status, type, page = 1, limit = 20 } = req.query;
    let expenses = [...db.accounts.expenses];
    
    if (status) expenses = expenses.filter(e => e.status === status);
    if (type) expenses = expenses.filter(e => e.type === type);
    
    const total = expenses.length;
    const start = (page - 1) * limit;
    const data = expenses.slice(start, start + parseInt(limit));
    
    res.json({ success: true, data, total, page: parseInt(page), limit: parseInt(limit) });
});

app.post('/api/finance/expenses/:id/approve', authMiddleware, (req, res) => {
    const expense = db.accounts.expenses.find(e => e.id === req.params.id);
    if (!expense) {
        return res.status(404).json({ success: false, message: '报销单不存在' });
    }
    
    expense.status = 'approved';
    expense.approvedAt = new Date().toISOString();
    expense.approvedBy = req.user.id;
    saveData('accounts');
    
    res.json({ success: true, data: expense, message: '报销审批成功' });
});

// ==================== AI辅助接口 ====================
app.post('/api/ai/generate-description', authMiddleware, async (req, res) => {
    const { sku, features, language } = req.body;
    
    // 模拟AI生成商品描述
    const description = {
        sku,
        title: `${features.productName} - 高品质${features.category}`,
        bulletPoints: [
            `【产品特点】${features.highlights?.join('、') || '优质材料，精工制作'}`,
            `【适用场景】${features.scenario || '日常使用，商务办公'}`,
            `【品质保证】通过严格质量检测，值得信赖`,
            `【售后服务】提供完善的售后支持`
        ],
        description: `这款${features.productName}采用优质材料制作，${features.description || '精心设计，品质卓越'}。适合${features.scenario || '各种场景'}使用，是您的理想选择。`,
        generatedAt: new Date().toISOString()
    };
    
    res.json({ success: true, data: description });
});

app.post('/api/ai/translate', authMiddleware, (req, res) => {
    const { text, sourceLang, targetLang } = req.body;
    
    // 模拟翻译（实际应调用翻译API）
    const translated = `[翻译结果: ${text}] - 已翻译为 ${targetLang}`;
    
    res.json({ success: true, data: { original: text, translated, targetLang } });
});

app.post('/api/ai/analyze-reviews', authMiddleware, (req, res) => {
    const { sku, reviews } = req.body;
    
    // 模拟差评分析
    const analysis = {
        sku,
        totalReviews: reviews?.length || 10,
        averageRating: 4.2,
        sentiment: {
            positive: 65,
            neutral: 20,
            negative: 15
        },
        keyIssues: [
            { issue: '包装问题', count: 5, severity: 'medium' },
            { issue: '物流时效', count: 3, severity: 'low' },
            { issue: '产品质量', count: 2, severity: 'high' }
        ],
        suggestions: [
            '建议优化包装方案，减少运输损坏',
            '考虑更换物流服务商或升级物流方案',
            '加强产品质量把控，减少差评率'
        ],
        analyzedAt: new Date().toISOString()
    };
    
    res.json({ success: true, data: analysis });
});

// ==================== 文件上传 ====================
const storage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, uploadDir),
    filename: (req, file, cb) => cb(null, `${Date.now()}_${file.originalname}`)
});

const upload = multer({ storage });

app.post('/api/upload', authMiddleware, upload.single('file'), (req, res) => {
    if (!req.file) {
        return res.status(400).json({ success: false, message: '未上传文件' });
    }
    res.json({
        success: true,
        data: {
            filename: req.file.filename,
            path: `/uploads/${req.file.filename}`,
            size: req.file.size
        }
    });
});

// ==================== 数据持久化 ====================
function saveData(key) {
    const filePath = path.join(dataDir, `${key}.js`);
    const content = `module.exports = ${JSON.stringify(db[key], null, 2)};`;
    fs.writeFileSync(filePath, content);
}

// ==================== 启动服务器 ====================
app.listen(PORT, () => {
    console.log(`
╔════════════════════════════════════════════════════════════╗
║                                                            ║
║   拓岳科技跨境电商管理系统 - 后端服务                      ║
║                                                            ║
║   服务地址: http://localhost:${PORT}                         ║
║   API文档:  http://localhost:${PORT}/api/docs               ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
    `);
});

// API文档路由
app.get('/api/docs', (req, res) => {
    res.send(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>拓岳电商系统 API文档</title>
            <style>
                body { font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; }
                h1 { color: #1890ff; }
                h2 { color: #333; border-bottom: 2px solid #1890ff; padding-bottom: 10px; }
                .endpoint { background: #f5f5f5; padding: 15px; margin: 10px 0; border-radius: 8px; }
                .method { display: inline-block; padding: 4px 12px; border-radius: 4px; font-weight: bold; margin-right: 10px; }
                .get { background: #61affe; color: white; }
                .post { background: #49cc90; color: white; }
                .put { background: #fca130; color: white; }
                .delete { background: #f93e3e; color: white; }
                code { background: #e8e8e8; padding: 2px 6px; border-radius: 4px; }
            </style>
        </head>
        <body>
            <h1>🚀 拓岳电商系统 API文档</h1>
            
            <h2>认证接口</h2>
            <div class="endpoint"><span class="method post">POST</span><code>/api/auth/login</code> - 用户登录</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/auth/register</code> - 用户注册</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/auth/profile</code> - 获取用户信息</div>
            
            <h2>销售管理</h2>
            <div class="endpoint"><span class="method get">GET</span><code>/api/sales/orders</code> - 获取订单列表</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/sales/orders/:id</code> - 获取订单详情</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/sales/orders</code> - 创建订单</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/sales/orders/:id/audit</code> - 订单审核</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/sales/orders/:id/split</code> - 订单拆分</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/sales/orders/merge</code> - 订单合并</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/sales/orders/:id/mark-exception</code> - 异常标记</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/sales/listings</code> - 获取Listing列表</div>
            <div class="endpoint"><span class="method put">PUT</span><code>/api/sales/listings/:id/price</code> - 调价</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/sales/listings/:id/publish</code> - 刊登</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/sales/aftersales</code> - 获取售后列表</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/sales/aftersales/analytics</code> - 售后数据分析</div>
            
            <h2>产品与库存</h2>
            <div class="endpoint"><span class="method get">GET</span><code>/api/products</code> - 获取产品列表</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/products</code> - 创建产品</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/products/:id/link-source</code> - 货源配对</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/inventory</code> - 获取库存列表</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/inventory/summary</code> - 库存汇总</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/inventory/transactions</code> - 出入库操作</div>
            
            <h2>FBA仓储与补货</h2>
            <div class="endpoint"><span class="method get">GET</span><code>/api/fba/replenishment/suggestions</code> - 补货建议</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/fba/replenishment/calculate</code> - 计算补货</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/fba/shipments</code> - 货件列表</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/fba/shipments</code> - 创建货件</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/fba/shipments/:id/boxing</code> - 装箱任务</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/fba/shipments/:id/tracking</code> - 跟踪号同步</div>
            
            <h2>物流与供应链</h2>
            <div class="endpoint"><span class="method get">GET</span><code>/api/logistics/channels</code> - 物流渠道</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/logistics/calculate-freight</code> - 运费试算</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/logistics/print-label</code> - 面单打印</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/logistics/tracking/:trackingNumber</code> - 物流轨迹</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/purchases</code> - 采购单列表</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/purchases</code> - 创建采购单</div>
            <div class="endpoint"><span class="method put">PUT</span><code>/api/purchases/:id/stage/:stage</code> - 更新阶段状态</div>
            
            <h2>财务管理</h2>
            <div class="endpoint"><span class="method get">GET</span><code>/api/finance/profit-report</code> - 利润报表</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/finance/profit-summary</code> - 利润汇总</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/finance/accounts-payable</code> - 应付账款</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/finance/platform-revenue</code> - 平台收款</div>
            <div class="endpoint"><span class="method get">GET</span><code>/api/finance/expenses</code> - 费用报销</div>
            
            <h2>AI辅助</h2>
            <div class="endpoint"><span class="method post">POST</span><code>/api/ai/generate-description</code> - 生成商品描述</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/ai/translate</code> - 多语言翻译</div>
            <div class="endpoint"><span class="method post">POST</span><code>/api/ai/analyze-reviews</code> - 差评分析</div>
        </body>
        </html>
    `);
});
