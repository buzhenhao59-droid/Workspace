module.exports = [
    {
        id: 'PO_20260303_001',
        supplierId: 'SUP_001',
        supplierName: '深圳供应商A',
        items: [
            { sku: 'SKU-001', name: '无线蓝牙耳机', quantity: 500, unitPrice: 25.00 }
        ],
        totalAmount: 12500,
        currency: 'CNY',
        status: 'processing',
        stages: {
            inbound: { status: 'completed', completedAt: '2026-03-02T10:00:00.000Z' },
            qualityCheck: { status: 'completed', completedAt: '2026-03-02T14:00:00.000Z' },
            reconciliation: { status: 'issue', notes: '发票金额不符', issues: ['发票金额与订单金额不符，差额500元'] }
        },
        createdAt: '2026-03-01T00:00:00.000Z'
    },
    {
        id: 'PO_20260302_002',
        supplierId: 'SUP_002',
        supplierName: '广州供应商B',
        items: [
            { sku: 'SKU-002', name: '智能手表', quantity: 300, unitPrice: 93.33 }
        ],
        totalAmount: 28000,
        currency: 'CNY',
        status: 'completed',
        stages: {
            inbound: { status: 'completed', completedAt: '2026-03-01T10:00:00.000Z' },
            qualityCheck: { status: 'completed', completedAt: '2026-03-01T14:00:00.000Z' },
            reconciliation: { status: 'completed', completedAt: '2026-03-01T16:00:00.000Z' }
        },
        createdAt: '2026-02-28T00:00:00.000Z'
    }
];
