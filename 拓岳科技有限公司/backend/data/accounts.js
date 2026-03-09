module.exports = {
    payable: [
        {
            id: 'AP_001',
            supplierId: 'SUP_001',
            supplierName: '深圳供应商A',
            amount: 12500,
            currency: 'CNY',
            dueDate: '2026-03-15',
            status: 'pending',
            purchaseOrderId: 'PO_20260303_001',
            createdAt: '2026-03-01T00:00:00.000Z'
        },
        {
            id: 'AP_002',
            supplierId: 'SUP_002',
            supplierName: '广州供应商B',
            amount: 28000,
            currency: 'CNY',
            dueDate: '2026-03-10',
            status: 'paid',
            purchaseOrderId: 'PO_20260302_002',
            paidAt: '2026-03-05T00:00:00.000Z',
            createdAt: '2026-02-28T00:00:00.000Z'
        }
    ],
    platformRevenue: [
        {
            id: 'PR_001',
            platform: '亚马逊',
            marketplace: '美国',
            amount: 28500.00,
            currency: 'USD',
            period: '2026-03-01至2026-03-15',
            status: 'pending',
            estimatedPayout: '2026-03-20',
            createdAt: '2026-03-01T00:00:00.000Z'
        },
        {
            id: 'PR_002',
            platform: '亚马逊',
            marketplace: '欧洲',
            amount: 156800.00,
            currency: 'USD',
            period: '2026-02-01至2026-02-28',
            status: 'settled',
            settledAt: '2026-03-05T00:00:00.000Z',
            createdAt: '2026-02-01T00:00:00.000Z'
        }
    ],
    expenses: [
        {
            id: 'EXP_001',
            type: 'office',
            description: '办公用品采购',
            amount: 3500,
            currency: 'CNY',
            applicant: '张三',
            status: 'pending',
            createdAt: '2026-03-02T00:00:00.000Z'
        },
        {
            id: 'EXP_002',
            type: 'travel',
            description: '出差报销-广州展会',
            amount: 8850,
            currency: 'CNY',
            applicant: '李四',
            status: 'approved',
            approvedAt: '2026-03-01T00:00:00.000Z',
            createdAt: '2026-02-28T00:00:00.000Z'
        },
        {
            id: 'EXP_003',
            type: 'marketing',
            description: '推广费用',
            amount: 45600,
            currency: 'CNY',
            applicant: '王五',
            status: 'approved',
            approvedAt: '2026-02-25T00:00:00.000Z',
            createdAt: '2026-02-20T00:00:00.000Z'
        }
    ]
};
