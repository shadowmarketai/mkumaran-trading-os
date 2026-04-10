import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain,
  Loader2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Building2,
  TrendingUp,
  Shield,
  BarChart3,
  Microscope,
  LineChart,
  Globe,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import { cn } from '../lib/utils';
import api from '../services/api';

interface ToolConfig {
  id: string;
  name: string;
  firm: string;
  description: string;
  endpoint: string;
  icon: React.ReactNode;
  color: string;
  fields: ToolField[];
}

interface ToolField {
  name: string;
  label: string;
  type: 'text' | 'textarea';
  placeholder: string;
  required?: boolean;
}

const wallStreetTools: ToolConfig[] = [
  {
    id: 'fundamental',
    name: 'Fundamental Screen',
    firm: 'Goldman Sachs',
    description: 'Deep fundamental analysis with financial ratios, growth metrics, and valuation multiples',
    endpoint: '/tools/wallstreet/fundamental_screen',
    icon: <Building2 size={20} />,
    color: 'from-yellow-500 to-amber-600',
    fields: [
      { name: 'ticker', label: 'Ticker', type: 'text', placeholder: 'e.g., RELIANCE', required: true },
      { name: 'company_name', label: 'Company Name', type: 'text', placeholder: 'e.g., Reliance Industries' },
    ],
  },
  {
    id: 'dcf',
    name: 'DCF Valuation',
    firm: 'Morgan Stanley',
    description: 'Discounted cash flow model with intrinsic value estimation and margin of safety',
    endpoint: '/tools/wallstreet/dcf_valuation',
    icon: <TrendingUp size={20} />,
    color: 'from-blue-500 to-indigo-600',
    fields: [
      { name: 'ticker', label: 'Ticker', type: 'text', placeholder: 'e.g., TCS', required: true },
      { name: 'company_name', label: 'Company Name', type: 'text', placeholder: 'e.g., Tata Consultancy' },
    ],
  },
  {
    id: 'risk',
    name: 'Risk Report',
    firm: 'Bridgewater',
    description: 'All Weather portfolio risk analysis with correlation matrix and drawdown scenarios',
    endpoint: '/tools/wallstreet/risk_report',
    icon: <Shield size={20} />,
    color: 'from-red-500 to-rose-600',
    fields: [
      { name: 'portfolio_tickers', label: 'Portfolio Tickers (comma-separated)', type: 'text', placeholder: 'e.g., RELIANCE,TCS,INFY,SBIN', required: true },
    ],
  },
  {
    id: 'earnings',
    name: 'Pre-Earnings Brief',
    firm: 'JPMorgan',
    description: 'Comprehensive pre-earnings analysis with consensus estimates and historical reactions',
    endpoint: '/tools/wallstreet/earnings_brief',
    icon: <BarChart3 size={20} />,
    color: 'from-emerald-500 to-green-600',
    fields: [
      { name: 'ticker', label: 'Ticker', type: 'text', placeholder: 'e.g., INFY', required: true },
      { name: 'company_name', label: 'Company Name', type: 'text', placeholder: 'e.g., Infosys Ltd' },
    ],
  },
  {
    id: 'technical',
    name: 'Technical Summary',
    firm: 'Citadel',
    description: '3-sentence institutional technical summary with key levels and momentum signals',
    endpoint: '/tools/wallstreet/technical_summary',
    icon: <LineChart size={20} />,
    color: 'from-purple-500 to-violet-600',
    fields: [
      { name: 'ticker', label: 'Ticker', type: 'text', placeholder: 'e.g., HDFCBANK', required: true },
      { name: 'ohlcv_summary', label: 'OHLCV Summary (optional)', type: 'textarea', placeholder: 'Paste OHLCV context...' },
    ],
  },
  {
    id: 'sector',
    name: 'Sector Analysis',
    firm: 'Bain',
    description: 'Competitive sector analysis with peer comparison and market positioning',
    endpoint: '/tools/wallstreet/sector_analysis',
    icon: <Microscope size={20} />,
    color: 'from-orange-500 to-amber-600',
    fields: [
      { name: 'ticker', label: 'Ticker', type: 'text', placeholder: 'e.g., TATASTEEL', required: true },
      { name: 'company_name', label: 'Company Name', type: 'text', placeholder: 'e.g., Tata Steel' },
    ],
  },
  {
    id: 'macro',
    name: 'Macro Assessment',
    firm: 'McKinsey',
    description: 'Macro sector rotation assessment with economic indicators and cycle positioning',
    endpoint: '/tools/wallstreet/macro_assessment',
    icon: <Globe size={20} />,
    color: 'from-cyan-500 to-teal-600',
    fields: [],
  },
];

interface ToolCardProps {
  tool: ToolConfig;
}

function ToolCard({ tool }: ToolCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    const missingRequired = tool.fields
      .filter((f) => f.required && !formValues[f.name]?.trim())
      .map((f) => f.label);

    if (missingRequired.length > 0) {
      setError(`Required: ${missingRequired.join(', ')}`);
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const resp = await api.post(tool.endpoint, null, { params: formValues });
      setResult(resp.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <GlassCard className="overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between"
      >
        <div className="flex items-center gap-3">
          <div className={cn('w-10 h-10 rounded-lg bg-gradient-to-br flex items-center justify-center text-white', tool.color)}>
            {tool.icon}
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-slate-900">{tool.name}</h3>
            <p className="text-xs text-slate-500">{tool.firm}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 hidden sm:block">{tool.description.slice(0, 50)}...</span>
          {expanded ? <ChevronUp size={16} className="text-slate-500" /> : <ChevronDown size={16} className="text-slate-500" />}
        </div>
      </button>

      {/* Expanded Content */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="pt-4 mt-4 border-t border-slate-200 space-y-5">
              <p className="text-sm text-slate-500">{tool.description}</p>

              {/* Input Fields */}
              {tool.fields.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {tool.fields.map((field) => (
                    <div key={field.name} className={field.type === 'textarea' ? 'md:col-span-2' : ''}>
                      <label className="stat-label block mb-1">
                        {field.label} {field.required && <span className="text-trading-bear">*</span>}
                      </label>
                      {field.type === 'textarea' ? (
                        <textarea
                          value={formValues[field.name] || ''}
                          onChange={(e) => setFormValues({ ...formValues, [field.name]: e.target.value })}
                          placeholder={field.placeholder}
                          rows={3}
                          className="w-full bg-slate-50 border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono tabular-nums text-slate-900 placeholder-slate-400 focus:outline-none focus:border-trading-ai/40 resize-none"
                        />
                      ) : (
                        <input
                          type="text"
                          value={formValues[field.name] || ''}
                          onChange={(e) => setFormValues({ ...formValues, [field.name]: e.target.value })}
                          placeholder={field.placeholder}
                          className="w-full bg-slate-50 border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono tabular-nums text-slate-900 placeholder-slate-400 focus:outline-none focus:border-trading-ai/40"
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Run Button */}
              <button
                onClick={handleRun}
                disabled={loading}
                className={cn(
                  'flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all',
                  loading ? 'bg-violet-50 text-slate-500 cursor-wait border border-violet-200' : 'gradient-ai text-white hover:opacity-90'
                )}
              >
                {loading ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Analyzing...
                  </>
                ) : (
                  <>
                    <Brain size={14} />
                    Run Analysis
                  </>
                )}
              </button>

              {/* Error */}
              {error && (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200">
                  <AlertCircle size={14} className="text-trading-bear" />
                  <p className="text-sm text-trading-bear">{error}</p>
                </div>
              )}

              {/* Result */}
              {result && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="p-4 rounded-lg bg-slate-50 border border-slate-200"
                >
                  <h4 className="stat-label mb-2">Result</h4>
                  <pre className="text-xs font-mono tabular-nums text-slate-600 whitespace-pre-wrap overflow-x-auto max-h-96 overflow-y-auto">
                    {JSON.stringify(result, null, 2)}
                  </pre>
                </motion.div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </GlassCard>
  );
}

export default function WallStreetPage() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-5"
    >
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2">
          <Brain size={22} className="text-trading-ai" />
          Wall Street AI Tools
        </h2>
        <p className="text-sm text-slate-500 mt-0.5">
          10 institutional-grade AI analysis tools powered by Wall Street methodologies
        </p>
      </div>

      {/* Tool Cards */}
      <div className="space-y-3">
        {wallStreetTools.map((tool) => (
          <ToolCard key={tool.id} tool={tool} />
        ))}
      </div>
    </motion.div>
  );
}
