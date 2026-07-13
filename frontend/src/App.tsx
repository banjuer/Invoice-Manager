import { useState, useEffect, useMemo } from 'react';
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import UploadPage from './pages/UploadPage';
import InvoiceListPage from './pages/InvoiceListPage';
import InvoiceDetailPage from './pages/InvoiceDetailPage';
import LLMConfigModal from './components/LLMConfigModal';
import { MainLayout } from './components/layout';
import { getLLMStatus } from './services/api';

function AppContent() {
  const location = useLocation();
  const [llmConfigOpen, setLlmConfigOpen] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);
  const [showLlmPromo, setShowLlmPromo] = useState(false);

  // Standalone mode: opened via /invoices/number/:number — no sidebar
  const isStandaloneDetail = useMemo(
    () => location.pathname.startsWith('/invoices/number/'),
    [location.pathname]
  );

  // Check LLM status on app load
  useEffect(() => {
    const checkLLMStatus = async () => {
      try {
        const status = await getLLMStatus();
        setLlmConfigured(status.is_configured);
        // Show promotion banner if LLM is not configured (non-blocking)
        if (!status.is_configured) {
          setShowLlmPromo(true);
        }
      } catch (error) {
        console.error('Failed to check LLM status:', error);
        // If check fails, assume not configured
        setLlmConfigured(false);
        setShowLlmPromo(true);
      }
    };
    checkLLMStatus();
  }, []);

  const handleLLMConfigured = () => {
    setLlmConfigured(true);
    setShowLlmPromo(false);
  };

  const routes = (
    <Routes>
      <Route path="/" element={<InvoiceListPage />} />
      <Route path="/upload" element={<UploadPage />} />
      <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
      <Route path="/invoices/number/:number" element={<InvoiceDetailPage />} />
    </Routes>
  );

  const llmModal = (
    <LLMConfigModal
      open={llmConfigOpen}
      onClose={() => setLlmConfigOpen(false)}
      onConfigured={handleLLMConfigured}
    />
  );

  // Standalone detail: render without sidebar/header
  if (isStandaloneDetail) {
    return (
      <>
        <main style={{ minHeight: '100vh', background: '#f5f5f5' }}>
          {routes}
        </main>
        {llmModal}
      </>
    );
  }

  return (
    <MainLayout
      llmConfigured={llmConfigured}
      showLlmPromo={showLlmPromo}
      onOpenLLMConfig={() => setLlmConfigOpen(true)}
      onCloseLLMPromo={() => setShowLlmPromo(false)}
    >
      {routes}
      {llmModal}
    </MainLayout>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}

export default App;
