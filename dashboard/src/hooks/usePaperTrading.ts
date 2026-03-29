import { useState, useEffect, useCallback } from 'react';
import type { OrderStatus, PlaceOrderRequest, OrderResult } from '../types';
import { orderApi } from '../services/api';

export function usePaperTrading(refreshInterval = 10000) {
  const [status, setStatus] = useState<OrderStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await orderApi.getStatus();
      setStatus(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch order status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, refreshInterval]);

  const placeOrder = useCallback(async (order: PlaceOrderRequest): Promise<OrderResult> => {
    const result = await orderApi.placeOrder(order);
    await fetchStatus();
    return result;
  }, [fetchStatus]);

  const cancelOrder = useCallback(async (orderId: string) => {
    const result = await orderApi.cancelOrder(orderId);
    await fetchStatus();
    return result;
  }, [fetchStatus]);

  const closePosition = useCallback(async (ticker: string) => {
    const result = await orderApi.closePosition(ticker);
    await fetchStatus();
    return result;
  }, [fetchStatus]);

  const closeAll = useCallback(async () => {
    const result = await orderApi.closeAll();
    await fetchStatus();
    return result;
  }, [fetchStatus]);

  return {
    status,
    loading,
    error,
    refetch: fetchStatus,
    placeOrder,
    cancelOrder,
    closePosition,
    closeAll,
  };
}
