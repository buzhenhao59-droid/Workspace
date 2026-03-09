module.exports = [
    {
        id: 'LIST_001',
        sku: 'SKU-001',
        name: '无线蓝牙耳机 Pro',
        shop: '店铺A',
        platform: '亚马逊',
        price: 45.99,
        status: 'online',
        stock: 256,
        category: '电子产品/音频',
        brand: 'SoundMax',
        publishedPlatforms: ['amazon_us', 'amazon_eu'],
        priceHistory: [
            { oldPrice: 49.99, newPrice: 45.99, reason: '促销活动', changedAt: '2026-03-01T10:00:00.000Z' }
        ],
        aplusContent: {
            title: 'SoundMax 无线蓝牙耳机 Pro - 高品质音效',
            images: ['/uploads/aplus_001_1.jpg', '/uploads/aplus_001_2.jpg'],
            description: '采用最新蓝牙5.0技术，支持主动降噪...'
        },
        createdAt: '2026-01-15T00:00:00.000Z'
    },
    {
        id: 'LIST_002',
        sku: 'SKU-002',
        name: '智能运动手表',
        shop: '店铺B',
        platform: '亚马逊',
        price: 78.00,
        status: 'online',
        stock: 89,
        category: '电子产品/穿戴',
        brand: 'TimeFit',
        publishedPlatforms: ['amazon_us'],
        createdAt: '2026-02-01T00:00:00.000Z'
    },
    {
        id: 'LIST_003',
        sku: 'SKU-003',
        name: '便携充电宝',
        shop: '店铺A',
        platform: '亚马逊',
        price: 22.50,
        status: 'online',
        stock: 450,
        category: '电子产品/配件',
        brand: 'PowerMax',
        publishedPlatforms: ['amazon_us', 'amazon_jp'],
        createdAt: '2026-01-20T00:00:00.000Z'
    }
];
