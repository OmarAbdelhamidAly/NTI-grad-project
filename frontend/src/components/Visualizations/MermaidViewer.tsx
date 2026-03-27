import { useEffect, useRef } from 'react';
import mermaid from 'mermaid';

interface MermaidViewerProps {
  chart: string;
}

// Initialize mermaid once
mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  securityLevel: 'loose',
  fontFamily: 'Inter, sans-serif',
  themeVariables: {
    primaryColor: '#6366f1',
    primaryTextColor: '#fff',
    primaryBorderColor: '#4338ca',
    lineColor: '#475569',
    secondaryColor: '#1e293b',
    tertiaryColor: '#0f172a'
  }
});

export default function MermaidViewer({ chart }: MermaidViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current && chart) {
      // Clear container
      containerRef.current.innerHTML = '';
      
      const renderDiagram = async () => {
        try {
            const id = `mermaid-${Math.random().toString(36).substring(7)}`;
            const { svg } = await mermaid.render(id, chart);
            if (containerRef.current) {
                containerRef.current.innerHTML = svg;
                
                // Make SVG responsive
                const svgElement = containerRef.current.querySelector('svg');
                if (svgElement) {
                    svgElement.style.width = '100%';
                    svgElement.style.height = 'auto';
                }
            }
        } catch (error) {
            console.error('Mermaid render error:', error);
            if (containerRef.current) {
                containerRef.current.innerHTML = `
                  <div class="p-8 text-center bg-red-500/10 border border-red-500/20 rounded-2xl">
                    <p class="text-xs font-black text-red-400 uppercase tracking-widest">Diagram Synchronization Failed</p>
                    <p class="text-[10px] text-slate-500 font-bold uppercase mt-2">Invalid ERD grammar detected in schema</p>
                  </div>
                `;
            }
        }
      };

      renderDiagram();
    }
  }, [chart]);

  return (
    <div className="w-full bg-slate-900/40 p-8 rounded-[32px] border border-slate-800/50 backdrop-blur-xl transition-all overflow-x-auto custom-scroll">
      <div ref={containerRef} className="mermaid-container flex justify-center" />
    </div>
  );
}
