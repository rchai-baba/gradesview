import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SyncProvider } from "@/contexts/SyncContext";
import Index from "./pages/Index.tsx";
import GradesHome from "./pages/GradesHome.tsx";
import ClassDetail from "./pages/ClassDetail.tsx";
import Config from "./pages/Config.tsx";
import NotFound from "./pages/NotFound.tsx";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <SyncProvider>
          <Routes>
            <Route path="/" element={<Index />} />
            <Route path="/grades" element={<GradesHome />} />
            <Route path="/config" element={<Config />} />
            <Route path="/class/:classId" element={<ClassDetail />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </SyncProvider>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
