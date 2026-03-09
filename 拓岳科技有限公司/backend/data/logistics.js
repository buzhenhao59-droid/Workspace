module.exports = {
    channels: [
        { id: 'DHL', name: 'DHL', baseRate: 45, currency: 'CNY', estimatedDays: '3-5', type: 'express' },
        { id: 'FedEx', name: 'FedEx', baseRate: 42, currency: 'CNY', estimatedDays: '3-5', type: 'express' },
        { id: 'UPS', name: 'UPS', baseRate: 40, currency: 'CNY', estimatedDays: '4-6', type: 'express' },
        { id: 'SF_INTL', name: '顺丰国际', baseRate: 35, currency: 'CNY', estimatedDays: '5-7', type: 'express' },
        { id: 'YUNTU', name: '云途物流', baseRate: 28, currency: 'CNY', estimatedDays: '7-10', type: 'special' },
        { id: 'YANWEN', name: '燕文物流', baseRate: 25, currency: 'CNY', estimatedDays: '10-15', type: 'economy' }
    ]
};
