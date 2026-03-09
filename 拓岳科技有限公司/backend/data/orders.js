module.exports = [
    {
        id: 'ORD_20260303_001',
        platform: '亚马逊',
        shopId: 'shop_001',
        orderNumber: 'AMZ-20260303-001',
        customer: { name: 'John Smith', email: 'john@example.com', address: '123 Main St, Los Angeles, CA 90001' },
        items: [
            { sku: 'SKU-001', name: '无线蓝牙耳机 Pro', quantity: 2, price: 44.99, total: 89.98 }
        ],
        subtotal: 89.98,
        shipping: 0,
        tax: 0,
        total: 89.99,
        status: 'audited',
        paymentStatus: 'paid',
        createdAt: '2026-03-03T08:30:00.000Z',
        auditedAt: '2026-03-03T09:00:00.000Z'
    },
    {
        id: 'ORD_20260303_002',
        platform: '亚马逊',
        shopId: 'shop_002',
        orderNumber: 'AMZ-20260303-002',
        customer: { name: 'Emma Wilson', email: 'emma@example.com', address: '456 Oak Ave, New York, NY 10001' },
        items: [
            { sku: 'SKU-002', name: '智能运动手表', quantity: 1, price: 156.00, total: 156.00 }
        ],
        subtotal: 156.00,
        shipping: 0,
        tax: 0,
        total: 156.00,
        status: 'pending',
        paymentStatus: 'paid',
        createdAt: '2026-03-03T10:15:00.000Z'
    },
    {
        id: 'ORD_20260303_003',
        platform: '亚马逊',
        shopId: 'shop_001',
        orderNumber: 'AMZ-20260303-003',
        customer: { name: 'Michael Brown', email: 'michael@example.com', address: '789 Pine Rd, Chicago, IL 60601' },
        items: [
            { sku: 'SKU-003', name: '便携充电宝', quantity: 3, price: 22.50, total: 67.50 }
        ],
        subtotal: 67.50,
        shipping: 0,
        tax: 0,
        total: 67.50,
        status: 'exception',
        exception: { reason: 'address_issue', description: '地址信息不完整', markedAt: '2026-03-03T11:00:00.000Z' },
        paymentStatus: 'paid',
        createdAt: '2026-03-03T09:45:00.000Z'
    }
];
