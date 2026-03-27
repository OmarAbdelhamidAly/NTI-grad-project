import { useState, useEffect } from 'react';
import { DataSourcesAPI } from '../../services/api';
import type { DataSource } from '../../services/api';
import {
  Database,
  Upload,
  Trash2,
  Plus,
  Search,
  FileText,
  BookOpen,
  Box,
  ShieldCheck,
  Users,
  Brain,
  Layout,
  LogOut,
  Mic,
  Activity,
  Loader2,
  Sparkles
} from 'lucide-react';
import { VoiceAPI } from '../../services/api';
import { recorder } from '../../utils/audio';
import ConnectModal from './ConnectModal';

interface SidebarProps {
  activeSourceIds: string[];
  onToggleSource: (id: string | null) => void;
  onSelectSource: (id: string | null) => void;
  currentView: string;
  onViewChange: (view: string) => void;
  user: any;
  onLogout: () => void;
}

export default function Sidebar({
  activeSourceIds,
  onToggleSource,
  onSelectSource,
  currentView,
  onViewChange,
  user,
  onLogout
}: SidebarProps) {
  const [sources, setSources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [isConnectModalOpen, setIsConnectModalOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [isRecording, setIsRecording] = useState(false);

  const handleVoiceSearch = async () => {
    if (isRecording) {
      try {
        const blob = await recorder.stop();
        setIsRecording(false);
        const { text } = await VoiceAPI.stt(blob);
        if (text) setSearchQuery(text);
      } catch (e) {
        console.error("STT failed", e);
        setIsRecording(false);
      }
    } else {
      try {
        await recorder.start();
        setIsRecording(true);
      } catch (e) {
        console.error("Mic access failed", e);
        alert("Microphone access denied or not supported.");
      }
    }
  };

  const fetchSources = async () => {
    try {
      setLoading(true);
      const data = await DataSourcesAPI.list();
      setSources(data);
    } catch (error) {
      console.error('Failed to load sources', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSources();
  }, []);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.length) return;
    const file = e.target.files[0];
    try {
      await DataSourcesAPI.upload(file);
      fetchSources();
    } catch (error) {
      console.error('Failed to upload file', error);
      alert('Upload failed.');
    } finally {
      e.target.value = '';
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this source?')) return;
    try {
      await DataSourcesAPI.delete(id);
      if (activeSourceIds.includes(id)) onToggleSource(id);
      fetchSources();
    } catch (error) {
      console.error('Failed to delete source', error);
    }
  };

  const filteredSources = sources.filter(s =>
    s.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const NavItem = ({ icon: Icon, label, color = "text-slate-400", id }: { icon: any, label: string, color?: string, id: string }) => (
    <button
      onClick={() => {
        onViewChange(id);
        onSelectSource(null); // Clear active source when switching to a general portal
      }}
      className={`
        w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all group text-left
        ${currentView === id
          ? 'bg-[var(--primary)]/10 border-[var(--primary)]/20 shadow-lg shadow-[var(--primary)]/5'
          : 'hover:bg-slate-800/40 border border-transparent'}
      `}
    >
      <Icon className={`w-4 h-4 ${currentView === id ? 'text-[var(--primary)]' : color}`} />
      <span className={`text-sm font-bold transition-colors ${currentView === id ? 'text-white' : 'text-slate-300 group-hover:text-white'}`}>
        {label}
      </span>
    </button>
  );

  const SectionHeader = ({ children }: { children: string }) => (
    <h3 className="text-[10px] font-black text-slate-600 uppercase tracking-[0.2em] mb-4 mt-8 px-3">
      {children}
    </h3>
  );

  return (
    <aside className="w-80 border-r border-slate-800 bg-[#0a0d17] flex flex-col h-full z-10 shrink-0">
      {/* Brand & Search */}
      <div className="p-6 pb-2">
        <div className="flex items-center gap-3 mb-6 px-1">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center shadow-lg shadow-indigo-500/30" style={{ background: 'linear-gradient(135deg, #06B6D4, #6366F1)' }}>
            <span className="text-white font-black text-base leading-none" style={{ fontFamily: 'Inter, sans-serif' }}>Q</span>
          </div>
          <span className="font-black text-white" style={{ fontSize: '1rem', letterSpacing: '0.05em' }}>
            Open<span style={{ background: 'linear-gradient(135deg, #06B6D4, #6366F1)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Q</span>
          </span>
        </div>

        <div className="relative group">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 group-focus-within:text-indigo-400 transition-colors" />
          <input
            type="text"
            placeholder={isRecording ? "Listening..." : "Deep Research"}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={`w-full bg-[#151c2c]/40 border rounded-2xl py-3 pl-11 pr-12 text-sm font-bold text-white placeholder:text-slate-600 focus:outline-none transition-all ${isRecording ? 'border-red-500/50 bg-red-500/5 shadow-[0_0_15px_rgba(239,68,68,0.1)]' : 'border-slate-800 focus:border-[var(--primary)]/50 focus:bg-[var(--primary)]/5'}`}
          />
          <button
            onClick={handleVoiceSearch}
            className={`absolute right-3 top-1/2 -translate-y-1/2 p-2 rounded-xl transition-all ${isRecording ? 'text-red-500 bg-red-500/10 animate-pulse' : 'text-slate-500 hover:text-[var(--primary)] hover:bg-[var(--primary)]/10'}`}
          >
            {isRecording ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mic className="w-4 h-4" />}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-2 custom-scroll">
        <SectionHeader>Master Hub</SectionHeader>
        <div className="space-y-1">
          <NavItem id="dashboard" icon={Sparkles} label="Sovereign Intelligence" color="text-amber-400" />
          <NavItem id="neural-feed" icon={Activity} label="Neural Feed" color="text-indigo-400" />
        </div>

        <SectionHeader>Service Portals</SectionHeader>
        <div className="space-y-1">
          <NavItem id="csv" icon={FileText} label="CSV Center" color="text-slate-400" />
          <NavItem id="sql" icon={Database} label="SQL Oracle" color="text-indigo-400" />
          <NavItem id="pdf" icon={BookOpen} label="PDF Insight" color="text-red-400" />
          <NavItem id="json" icon={Box} label="JSON Mapper" color="text-orange-400" />
        </div>

        <SectionHeader>Governance</SectionHeader>
        <div className="space-y-1">
          <NavItem id="governance" icon={ShieldCheck} label="Safety Protocols" />
          <NavItem id="knowledge" icon={Brain} label="Intelligence Hub" color="text-indigo-400" />
          <NavItem id="team" icon={Users} label="Team Management" />
        </div>

        <SectionHeader>System</SectionHeader>
        <div className="space-y-1">
          <NavItem id="system" icon={Layout} label="Tech Architecture" color="text-blue-400" />
        </div>

        {/* Dynamic Connections Section */}
        <div className="mt-8">
          <div className="flex items-center justify-between mb-4 px-3">
            <h3 className="text-[10px] font-black text-slate-600 uppercase tracking-[0.2em]">Data streams</h3>
            <span className="text-[10px] text-slate-500 font-bold">{sources.length}</span>
          </div>

          <div className="space-y-2 mb-4">
            {loading ? (
              <div className="p-3 text-slate-500 text-[10px] font-bold uppercase animate-pulse">Syncing...</div>
            ) : filteredSources.length === 0 ? (
              <div className="p-6 rounded-2xl border border-dashed border-slate-800/50 flex flex-col items-center text-center gap-2">
                <Database className="w-6 h-6 text-slate-800" />
                <p className="text-[9px] text-slate-600 font-bold uppercase">No data loaded</p>
              </div>
            ) : (
              filteredSources.map((source) => {
                const isActive = activeSourceIds.includes(source.id);
                return (
                  <div
                    key={source.id}
                    onClick={() => {
                      onToggleSource(source.id);
                      onViewChange('dashboard');
                    }}
                    className={`
                      group flex items-center justify-between p-3 rounded-xl cursor-pointer transition-all duration-300 border
                      ${isActive
                        ? 'bg-[var(--primary)]/10 border-[var(--primary)]/30 shadow-lg shadow-[var(--primary)]/5'
                        : 'bg-slate-900/30 border-transparent hover:border-slate-700/50 hover:bg-slate-800/40'}
                    `}
                  >
                    <div className="flex items-center gap-3 truncate">
                      <div className={`p-1.5 rounded-lg ${isActive ? 'bg-[var(--primary)] text-white' : 'bg-slate-800 text-slate-500'}`}>
                        {source.type === 'csv' && <FileText className="w-3 h-3" />}
                        {source.type === 'sql' && <Database className="w-3 h-3" />}
                        {source.type === 'pdf' && <BookOpen className="w-3 h-3" />}
                        {source.type === 'json' && <Box className="w-3 h-3" />}
                      </div>
                      <span className={`text-xs font-bold truncate ${isActive ? 'text-white' : 'text-slate-400'}`}>
                        {source.name}
                      </span>
                    </div>
                    <button
                      onClick={(e) => handleDelete(e, source.id)}
                      className="opacity-0 group-hover:opacity-100 p-1.5 text-slate-600 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-all"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                );
              })
            )}
          </div>

          <div className="grid grid-cols-2 gap-2 mt-4 px-1">
            <label className="flex items-center justify-center gap-2 p-3 border border-slate-800/50 rounded-xl bg-slate-900/20 text-slate-500 hover:text-[var(--primary)] hover:bg-[var(--primary)]/5 hover:border-[var(--primary)]/30 transition-all cursor-pointer group">
              <Upload className="w-3.5 h-3.5" />
              <span className="text-[10px] font-black uppercase tracking-tight">Upload</span>
              <input type="file" className="hidden" onChange={handleFileUpload} accept=".sqlite,.db,.csv,.xlsx,.pdf,.json" />
            </label>
            <button
              onClick={() => setIsConnectModalOpen(true)}
              className="flex items-center justify-center gap-2 p-3 border border-slate-800/50 rounded-xl bg-slate-900/20 text-slate-500 hover:text-[var(--primary)] hover:bg-[var(--primary)]/5 hover:border-[var(--primary)]/30 transition-all group"
            >
              <Plus className="w-3.5 h-3.5" />
              <span className="text-[10px] font-black uppercase tracking-tight">Connect</span>
            </button>
          </div>
        </div>
      </div>

      {/* Account Section */}
      <div className="p-4 mt-auto">
        <div className="bg-[#151c2c]/60 border border-slate-800/80 rounded-[24px] p-3 pr-10 relative group">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-[14px] bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-xs font-black text-white shadow-xl shadow-indigo-500/10">
              {user?.email?.charAt(0).toUpperCase() || 'O'}M
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[11px] font-black text-white truncate uppercase tracking-tight">
                {user?.email?.split('@')[0] || 'omar.yaser'}
              </p>
              <p className="text-[8px] text-[var(--primary)] font-black uppercase tracking-widest mt-0.5">
                PRO MEMBER
              </p>
            </div>
          </div>

          <button
            onClick={onLogout}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-slate-600 hover:text-red-400 hover:bg-red-400/10 rounded-xl transition-all"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>

      <ConnectModal
        isOpen={isConnectModalOpen}
        onClose={() => setIsConnectModalOpen(false)}
        onSuccess={fetchSources}
      />
    </aside>
  );
}
