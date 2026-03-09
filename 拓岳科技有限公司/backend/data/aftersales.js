module.exports = [
    {
        id: 'AS_001',
        type: 'refund_return',
        orderId: 'ORD_20260301_045',
        customer: 'John D.',
        reason: '商品有划痕',
        description: '收到商品后发现表面有明显划痕',
        status: 'processing',
        refundAmount: 89.99,
        items: [{ sku: 'SKU-001', name: '无线蓝牙耳机 Pro', quantity: 1 }],
        createdAt: '2026-03-03T08:00:00.000Z'
    },
    {
        id: 'AS_002',
        type: 'refund_only',
        orderId: 'ORD_20260228_112',
        customer: 'Emma W.',
        reason: '未收到配件',
        description: '包装内缺少充电线',
        status: 'completed',
        refundAmount: 15.00,
        items: [{ sku: 'SKU-002', name: '智能运动手表', quantity: 1 }],
        createdAt: '2026-03-02T14:30:00.000Z',
        processedAt: '2026-03-02T16:00:00.000Z'
    }
];
