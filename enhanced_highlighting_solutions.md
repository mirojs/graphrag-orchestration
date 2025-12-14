# Enhanced In-Line Text Highlighting Solutions

## 1. Canvas-Based Overlay System (Recommended) ⭐

### Implementation Approach
```typescript
interface CanvasHighlightSystem {
  // Create a transparent canvas overlay that sits directly on top of documents
  canvas: HTMLCanvasElement;
  coordinates: BoundingBox[];
  highlightRenderer: CanvasRenderingContext2D;
}

// Key Benefits:
// ✅ Works with ALL file types (PDF, Office, Images)
// ✅ Pixel-perfect positioning using Azure coordinate data
// ✅ No iframe restrictions
// ✅ Real-time highlighting with animations
// ✅ Responsive to zoom/pan operations
```

### Technical Implementation
```typescript
const createCanvasHighlightOverlay = (
  containerRef: React.RefObject<HTMLDivElement>,
  highlights: TextHighlight[],
  documentDimensions: { width: number; height: number }
) => {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  
  // Set canvas to match document container exactly
  canvas.style.position = 'absolute';
  canvas.style.top = '0';
  canvas.style.left = '0';
  canvas.style.pointerEvents = 'none';
  canvas.style.zIndex = '1000';
  
  // High-DPI support
  const devicePixelRatio = window.devicePixelRatio || 1;
  canvas.width = documentDimensions.width * devicePixelRatio;
  canvas.height = documentDimensions.height * devicePixelRatio;
  canvas.style.width = `${documentDimensions.width}px`;
  canvas.style.height = `${documentDimensions.height}px`;
  
  ctx.scale(devicePixelRatio, devicePixelRatio);
  
  // Render highlights with confidence-based styling
  highlights.forEach((highlight, index) => {
    if (highlight.boundingBox) {
      const { x, y, width, height } = highlight.boundingBox;
      const confidence = highlight.confidence || 0.8;
      
      // Confidence-based color intensity
      const alpha = Math.max(0.3, confidence);
      const strokeAlpha = Math.max(0.6, confidence);
      
      // Gradient fill for better visibility
      const gradient = ctx.createLinearGradient(x, y, x + width, y + height);
      gradient.addColorStop(0, `rgba(255, 255, 0, ${alpha})`);
      gradient.addColorStop(1, `rgba(255, 193, 7, ${alpha})`);
      
      ctx.fillStyle = gradient;
      ctx.fillRect(x, y, width, height);
      
      // Border with pulsing animation for exact matches
      if (highlight.type === 'exact') {
        ctx.strokeStyle = `rgba(255, 0, 0, ${strokeAlpha})`;
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 5]);
        ctx.strokeRect(x, y, width, height);
        
        // Add animation frame for pulsing effect
        animatePulsingBorder(ctx, { x, y, width, height }, index);
      }
      
      // Add confidence indicator
      ctx.fillStyle = '#333';
      ctx.font = '12px Arial';
      ctx.fillText(`${Math.round(confidence * 100)}%`, x + width + 5, y + 15);
    }
  });
  
  return canvas;
};
```

## 2. SVG-Based Precision Highlighting ⭐

### Implementation Approach
```typescript
interface SVGHighlightSystem {
  // Use SVG overlays for vector-perfect highlighting
  svgOverlay: SVGElement;
  highlightPaths: SVGPathElement[];
  animationSupport: boolean;
}

// Key Benefits:
// ✅ Vector-based precision (scales perfectly)
// ✅ CSS animation support
// ✅ Interactive hover effects
// ✅ Accessibility friendly
// ✅ Works with responsive designs
```

### Technical Implementation
```typescript
const createSVGHighlightOverlay = (
  containerRef: React.RefObject<HTMLDivElement>,
  highlights: TextHighlight[]
) => {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.style.position = 'absolute';
  svg.style.top = '0';
  svg.style.left = '0';
  svg.style.width = '100%';
  svg.style.height = '100%';
  svg.style.pointerEvents = 'none';
  svg.style.zIndex = '1000';
  
  highlights.forEach((highlight, index) => {
    if (highlight.boundingBox) {
      const { x, y, width, height } = highlight.boundingBox;
      
      // Create highlight rectangle with rounded corners
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', x.toString());
      rect.setAttribute('y', y.toString());
      rect.setAttribute('width', width.toString());
      rect.setAttribute('height', height.toString());
      rect.setAttribute('rx', '3');
      rect.setAttribute('ry', '3');
      
      // Dynamic styling based on highlight type and confidence
      const confidence = highlight.confidence || 0.8;
      const fillColor = highlight.type === 'exact' ? 
        `rgba(255, 235, 59, ${confidence * 0.6})` : 
        `rgba(33, 150, 243, ${confidence * 0.4})`;
      
      rect.setAttribute('fill', fillColor);
      rect.setAttribute('stroke', highlight.type === 'exact' ? '#ff5722' : '#2196f3');
      rect.setAttribute('stroke-width', '2');
      
      // Add CSS animations
      rect.style.animation = highlight.type === 'exact' ? 
        'pulse-highlight 2s infinite' : 
        'fade-in-highlight 1s ease-out';
      
      // Add tooltip
      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = `"${highlight.text}" (${Math.round(confidence * 100)}% confidence)`;
      rect.appendChild(title);
      
      svg.appendChild(rect);
    }
  });
  
  return svg;
};
```

## 3. Document-Native Highlighting (PDF-Specific) 🔥

### PDF.js Integration
```typescript
// For PDFs, integrate directly with PDF.js rendering
const injectPDFNativeHighlighting = async (
  pdfUrl: string,
  highlights: TextHighlight[],
  containerRef: React.RefObject<HTMLDivElement>
) => {
  // Load PDF.js library
  const pdfjsLib = await import('pdfjs-dist');
  
  // Create custom PDF viewer with highlighting support
  const loadingTask = pdfjsLib.getDocument(pdfUrl);
  const pdf = await loadingTask.promise;
  
  for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
    const page = await pdf.getPage(pageNum);
    const viewport = page.getViewport({ scale: 1.0 });
    
    // Create canvas for PDF rendering
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    canvas.height = viewport.height;
    canvas.width = viewport.width;
    
    // Render PDF page
    await page.render({ canvasContext: context, viewport });
    
    // Get text content for precise positioning
    const textContent = await page.getTextContent();
    
    // Apply highlights directly to text items
    highlights.forEach(highlight => {
      const matchingTextItem = textContent.items.find(item => 
        item.str.includes(highlight.text)
      );
      
      if (matchingTextItem) {
        // Use PDF.js transform matrix for exact positioning
        const [x, y] = pdfjsLib.Util.transform(
          viewport.transform,
          [matchingTextItem.transform[4], matchingTextItem.transform[5]]
        );
        
        // Draw highlight directly on PDF canvas
        context.fillStyle = 'rgba(255, 255, 0, 0.4)';
        context.fillRect(x, y - matchingTextItem.height, 
                        matchingTextItem.width, matchingTextItem.height);
      }
    });
    
    containerRef.current?.appendChild(canvas);
  }
};
```

## 4. Office Document Text Extraction + Overlay 📄

### Microsoft Graph API Integration
```typescript
// Extract text content from Office documents and create precise overlays
const createOfficeDocumentHighlighting = async (
  documentUrl: string,
  highlights: TextHighlight[]
) => {
  // Option 1: Use Microsoft Graph API to extract text content
  const textContent = await fetch(`/api/office-text-extract?url=${documentUrl}`);
  const documentText = await textContent.text();
  
  // Option 2: Use Office.js API if available in iframe
  const officeAPI = (window as any).Office;
  if (officeAPI) {
    officeAPI.context.document.body.search(highlight.text, {
      highlightColor: 'yellow',
      matchCase: false,
      matchWholeWord: false
    });
  }
  
  // Option 3: Create overlay based on estimated text positions
  const textPositions = estimateTextPositions(documentText, highlights);
  return createSVGHighlightOverlay(containerRef, textPositions);
};
```

## 5. Image OCR Re-processing for Precise Coordinates 📸

### Enhanced Image Highlighting
```typescript
// Re-process images with Azure Computer Vision for exact coordinates
const createImagePreciseHighlighting = async (
  imageUrl: string,
  highlights: TextHighlight[],
  azureCredentials: AzureCredentials
) => {
  // Use Azure Computer Vision Read API for precise text detection
  const ocrResult = await azureComputerVision.read(imageUrl);
  
  // Match highlights with OCR results
  const preciseHighlights = highlights.map(highlight => {
    const matchingLine = ocrResult.readResults[0].lines.find(line =>
      line.text.toLowerCase().includes(highlight.text.toLowerCase())
    );
    
    if (matchingLine) {
      return {
        ...highlight,
        boundingBox: {
          x: matchingLine.boundingBox[0],
          y: matchingLine.boundingBox[1],
          width: matchingLine.boundingBox[2] - matchingLine.boundingBox[0],
          height: matchingLine.boundingBox[5] - matchingLine.boundingBox[1]
        },
        confidence: matchingLine.confidence || 0.9
      };
    }
    return highlight;
  });
  
  return createCanvasHighlightOverlay(containerRef, preciseHighlights, imageSize);
};
```

## 6. Multi-Tab Document Viewer (Alternative UI) 🔄

### Single Document Focus Approach
```typescript
// Instead of side-by-side, use tabbed interface for better focus
const MultiTabDocumentViewer = ({
  documents,
  highlights,
  inconsistencyData
}: MultiTabProps) => {
  const [activeTab, setActiveTab] = useState(0);
  
  return (
    <div className="multi-tab-document-viewer">
      {/* Enhanced tab navigation */}
      <div className="document-tabs">
        {documents.map((doc, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''}`}
            onClick={() => setActiveTab(index)}
            style={{
              backgroundColor: doc.hasHighlights ? '#fff3cd' : '#fff',
              border: doc.hasHighlights ? '2px solid #ffc107' : '1px solid #ddd'
            }}
          >
            {doc.icon} {doc.title}
            {doc.highlightCount > 0 && (
              <span className="highlight-badge">{doc.highlightCount}</span>
            )}
          </button>
        ))}
      </div>
      
      {/* Full-width document viewer with enhanced highlighting */}
      <div className="document-content">
        <EnhancedDocumentViewer
          document={documents[activeTab]}
          highlights={highlights.filter(h => h.documentIndex === activeTab)}
          highlightingMethod="canvas" // or "svg" or "native"
          showMinimap={true}
          showHighlightNavigation={true}
        />
      </div>
      
      {/* Floating highlight navigation */}
      <HighlightNavigationPanel
        highlights={highlights}
        onHighlightClick={(highlight) => scrollToHighlight(highlight)}
        showConfidenceScores={true}
      />
    </div>
  );
};
```

## 7. CSS Implementation Example

```css
/* Enhanced highlighting animations */
@keyframes pulse-highlight {
  0% { 
    opacity: 0.6; 
    transform: scale(1); 
    filter: drop-shadow(0 0 3px rgba(255, 235, 59, 0.8));
  }
  50% { 
    opacity: 0.9; 
    transform: scale(1.02); 
    filter: drop-shadow(0 0 8px rgba(255, 235, 59, 1));
  }
  100% { 
    opacity: 0.6; 
    transform: scale(1); 
    filter: drop-shadow(0 0 3px rgba(255, 235, 59, 0.8));
  }
}

@keyframes fade-in-highlight {
  0% { 
    opacity: 0; 
    transform: translateY(-5px); 
  }
  100% { 
    opacity: 0.7; 
    transform: translateY(0); 
  }
}

/* Responsive canvas overlay */
.document-highlight-canvas {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  z-index: 1000;
  transition: all 0.3s ease;
}

/* Highlight navigation panel */
.highlight-navigation {
  position: fixed;
  right: 20px;
  top: 50%;
  transform: translateY(-50%);
  background: rgba(255, 255, 255, 0.95);
  border-radius: 12px;
  padding: 15px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
  backdrop-filter: blur(10px);
  max-height: 60vh;
  overflow-y: auto;
  z-index: 2000;
}

.highlight-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-bottom: 5px;
}

.highlight-item:hover {
  background-color: #f8f9fa;
  transform: translateX(5px);
}

.highlight-confidence {
  background: linear-gradient(45deg, #4caf50, #8bc34a);
  color: white;
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: bold;
}
```

## Implementation Priority Recommendations

### Phase 1: Canvas-Based System (Week 1-2)
1. Implement canvas overlay for images and PDFs
2. Add confidence-based highlighting
3. Create responsive positioning system

### Phase 2: SVG Enhancement (Week 3)
1. Add SVG-based highlighting for vector precision
2. Implement CSS animations
3. Add interactive hover effects

### Phase 3: Document-Specific Optimizations (Week 4)
1. PDF.js native integration
2. Office document text extraction
3. Enhanced image OCR processing

### Phase 4: UI Alternative (Week 5)
1. Multi-tab document viewer
2. Highlight navigation panel
3. Minimap for large documents

This approach will provide significantly better in-line text highlighting compared to the current side-by-side popup approach, especially for PDF, image, and Office files.