module.exports = [
    {
        id: 'PROD_001',
        sku: 'SKU-001',
        name: '无线蓝牙耳机 Pro',
        category: '电子产品/音频',
        brand: 'SoundMax',
        images: ['/uploads/prod_001_1.jpg', '/uploads/prod_001_2.jpg'],
        specifications: {
            color: '黑色',
            weight: '250g',
            batteryLife: '30小时',
            connectivity: '蓝牙5.0'
        },
        sourceLinks: [
            { sourceType: '1688', sourceUrl: 'https://www.1688.com/item_001', sourceSku: '1688_BT_001', sourcePrice: 15.00 }
        ],
        createdAt: '2026-01-15T00:00:00.000Z'
    },
    {
        id: 'PROD_002',
        sku: 'SKU-002',
        name: '智能运动手表',
        category: '电子产品/穿戴',
        brand: 'TimeFit',
        images: ['/uploads/prod_002_1.jpg'],
        specifications: {
            color: '银色',
            weight: '45g',
            batteryLife: '7天',
            waterproof: 'IP68'
        },
        sourceLinks: [
            { sourceType: 'alibaba', sourceUrl: 'https://www.alibaba.com/item_002', sourceSku: 'ALI_WT_002', sourcePrice: 28.00 }
        ],
        createdAt: '2026-02-01T00:00:00.000Z'
    }
];
