module.exports = [
    {
        id: 'FBA_20260303_001',
        destination: '美国-CA',
        status: 'in_transit',
        items: [
            { sku: 'SKU-001', quantity: 300 },
            { sku: 'SKU-002', quantity: 200 }
        ],
        totalItems: 500,
        boxes: [
            { id: 'BOX_001', items: [{ sku: 'SKU-001', quantity: 20 }], weight: 5.2, dimensions: { length: 30, width: 20, height: 15 } }
        ],
        totalBoxes: 25,
        trackingNumber: 'YT456789012',
        carrier: '云途物流',
        estimatedArrival: '2026-03-10',
        createdAt: '2026-03-01T00:00:00.000Z'
    },
    {
        id: 'FBA_20260302_002',
        destination: '美国-TX',
        status: 'received',
        items: [
            { sku: 'SKU-003', quantity: 300 }
        ],
        totalItems: 300,
        totalBoxes: 15,
        trackingNumber: 'YT456789013',
        carrier: '云途物流',
        receivedAt: '2026-03-02T00:00:00.000Z',
        createdAt: '2026-02-25T00:00:00.000Z'
    }
];
