import React, { useState, useEffect, useRef } from 'react';
import './App.css';

// --- NOVA FUNÇÃO HELPER ANINHADA: Para lidar com URLs simples ---
// (Esta função é chamada por renderContentWithLinks)
const renderSimpleLinks = (textBlock, baseKey) => {
    // Regex simples para encontrar URLs (http/https)
    const simpleUrlRegex = /(https?:\/\/[^\s<>"]+)/g;
    if (typeof textBlock !== 'string' || !textBlock) {
        return []; // Retorna array vazio se não for string válida
    }
    const parts = textBlock.split(simpleUrlRegex).filter(part => part); // Divide e remove vazios
    const result = [];

    parts.forEach((part, index) => {
        // Verifica se a parte parece ser uma URL simples e começa com http
        if (simpleUrlRegex.test(part) && part.startsWith('http')) {
             // Limpeza simples para remover pontuação final
            let cleanedHref = part.replace(/[.,;!?]*$/, '');
            try {
                new URL(cleanedHref); // Valida
                result.push(
                    <a key={`${baseKey}-slink-${index}`} href={cleanedHref} target="_blank" rel="noopener noreferrer">
                        {cleanedHref}
                    </a>
                );
            } catch (_) {
                // Se inválida, renderiza como texto com quebras de linha
                result.push(...part.split('\n').map((line, lineIndex, arr) => (
                    <React.Fragment key={`${baseKey}-sinvalid-${index}-${lineIndex}`}>
                      {line}
                      {lineIndex < arr.length - 1 && <br />}
                    </React.Fragment>
                  )));
                console.warn(`URL simples inválida encontrada: ${cleanedHref} (original: ${part})`);
            }
        } else {
             // Se não for URL, renderiza como texto com quebras de linha
              result.push(...part.split('\n').map((line, lineIndex, arr) => (
                <React.Fragment key={`${baseKey}-stext-${index}-${lineIndex}`}>
                  {line}
                  {lineIndex < arr.length - 1 && <br />}
                </React.Fragment>
              )));
        }
    });
    return result; // Retorna um array de elementos React
};


// --- FUNÇÃO HELPER PRINCIPAL: Para renderizar links (Lida com Markdown [TEXT](URL) e URLs simples) ---
const renderContentWithLinks = (content) => {
    if (typeof content !== 'string') {
        return content || ''; // Retorna como está ou vazio
    }

    const result = [];
    let lastIndex = 0;

    // Regex principal: Procura por links Markdown [TEXT](URL)
    // Grupo 1: Texto do link (dentro de []) - Ignorado na renderização atual
    // Grupo 2: URL (dentro de ())
    const markdownLinkRegex = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;

    let match;

    // 1. Processa links Markdown primeiro
    while ((match = markdownLinkRegex.exec(content)) !== null) {
        const textBefore = content.substring(lastIndex, match.index);
        // const linkText = match[1]; // Texto dentro de [] (não estamos usando)
        const url = match[2];     // URL dentro de ()
        const matchIndex = match.index;

        // Adiciona o texto antes do link Markdown, processando URLs simples nele
        if (textBefore) {
            result.push(...renderSimpleLinks(textBefore, `text-before-md-${matchIndex}`));
        }

        // Adiciona o link Markdown como <a>, usando a URL extraída
        try {
            // Limpeza leve na URL extraída (remove pontuação final comum)
            let cleanedHref = url.replace(/[.,;!?]*$/, '');
            new URL(cleanedHref); // Valida
            result.push(
                <a key={`mdlink-${matchIndex}`} href={cleanedHref} target="_blank" rel="noopener noreferrer">
                    {/* Exibe a URL limpa como texto do link */}
                    {cleanedHref}
                </a>
            );
        } catch (_) {
            // Se a URL do Markdown for inválida, adiciona o texto original completo do match
            // e tenta encontrar links simples dentro dele como fallback
            result.push(...renderSimpleLinks(match[0], `invalid-md-${matchIndex}`));
            console.warn(`URL Markdown inválida encontrada: ${url} (original: ${match[0]})`);
        }

        lastIndex = markdownLinkRegex.lastIndex; // Atualiza índice para próxima busca
    }

    // 2. Processa o texto restante APÓS o último link Markdown
    const remainingText = content.substring(lastIndex);
    if (remainingText) {
        // Busca por URLs simples no texto restante
        result.push(...renderSimpleLinks(remainingText, `text-after-md`));
    }

    return result.length > 0 ? result : ''; // Retorna array de elementos ou string vazia
};



// --- FUNÇÃO HELPER: Para verificar se é mensagem de horários ---
const isTimeSlotMessage = (content) => {
    if (typeof content !== 'string') return false;
    const hasKeywords = content.toLowerCase().includes('horários disponíveis') || content.toLowerCase().includes('horários abaixo');
    const listItemRegex = /^\s*\d+[.)]?\s*(\d+\s+de\s+\w+\s+às\s+\d{1,2}:\d{2})/i;
    const slotMatches = content.split('\n').filter(line => listItemRegex.test(line.trim())).length;
    // Considera mensagem de slot apenas se tiver múltiplos matches (evita confirmação)
    return hasKeywords || slotMatches > 1;
};

// --- FUNÇÃO HELPER: Para extrair os horários ---
const parseTimeSlots = (content) => {
    if (typeof content !== 'string') return [];
    const lines = content.split('\n');
    const slots = [];
    // Regex focado no padrão exato "DD de Mês às HH:MM"
    const slotRegex = /(\d{1,2}\s+de\s+\w+\s+às\s+\d{1,2}:\d{2})/i;

    lines.forEach((line) => {
        const match = line.trim().match(slotRegex);
        // Garante que a linha começa com um número/marcador ou contém apenas o slot
        if (match && match[1]) {
              if (line.trim().startsWith(match[0]) || line.trim().match(/^\d+[.)]?\s+/) || line.trim() === match[0]) {
                slots.push(match[1].trim());
            }
        }
    });
    return [...new Set(slots)]; // Remove duplicados
};


function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState(null);

  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    const newSessionId = Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
    setSessionId(newSessionId);
    setMessages([{
      role: "assistant",
      content: "Olá! Sou seu assistente de vendas. Como posso ajudar?"
    }]);
  }, []);

  const handleSend = async () => {
    if (input.trim() && sessionId) {
      const userMessageContent = input;
      const newMessages = [...messages, { role: 'user', content: userMessageContent }];
      setMessages(newMessages);
      setInput('');

      try {
          const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, message: userMessageContent }),
          });

          if (!response.ok) {
            let errorBody = await response.text();
            try { errorBody = JSON.parse(errorBody); } catch (e) { /* não é JSON */ }
            console.error("API Error Response:", errorBody);
            throw new Error(`HTTP error! status: ${response.status}, message: ${errorBody.detail || response.statusText}`);
          }

          const data = await response.json();
          if (data && data.response) {
            setMessages(prevMessages => [...prevMessages, { role: 'assistant', content: data.response }]);
          } else {
              console.error("Resposta da API inesperada:", data);
              setMessages(prevMessages => [...prevMessages, { role: 'assistant', content: `Desculpe, recebi uma resposta inesperada do servidor.` }]);
          }
      } catch (error) {
          console.error("Fetch error:", error);
          setMessages(prevMessages => [...prevMessages, { 
            role: 'assistant',
            content: `Desculpe, ocorreu um erro ao conectar ao servidor: ${error.message}. Verifique se o backend está rodando.` }]);
      }
    }
  };


  return (
    <div className="App">
      <div className="chat-window">
        <div className="messages">
          {messages.map((msg, index) => {
              let contentToRender;
              // Verifica se msg.content existe e é uma string
              if (msg.content && typeof msg.content === 'string') {
                  // Tenta detectar se é uma mensagem de lista de horários
                  if (msg.role === 'assistant' && isTimeSlotMessage(msg.content)) {
                    const slots = parseTimeSlots(msg.content);
                    let introText = msg.content;
                    let afterText = '';

                    // Se conseguiu extrair slots, formata a lista
                    if (slots.length > 0) {
                        const firstSlotRaw = slots[0];
                        const firstSlotIndex = msg.content.indexOf(firstSlotRaw);
                        let lastSlotEndIndex = -1;

                        const lastSlotRaw = slots[slots.length - 1];
                        // Procura a ÚLTIMA ocorrência do último slot encontrado
                        const lastSlotActualIndex = msg.content.lastIndexOf(lastSlotRaw);

                        if(lastSlotActualIndex !== -1) {
                            lastSlotEndIndex = lastSlotActualIndex + lastSlotRaw.length;
                        }

                        if (firstSlotIndex !== -1) {
                            introText = msg.content.substring(0, firstSlotIndex);
                        } else {
                             // Fallback se não achar o primeiro slot
                              introText = msg.content.split(slots[0] || '%%%%%')[0] || msg.content;
                          }

                        if (lastSlotEndIndex !== -1 && lastSlotEndIndex < msg.content.length) {
                             // Pega o texto APÓS o último slot encontrado
                              afterText = msg.content.substring(lastSlotEndIndex).trim();
                          } else {
                              afterText = ''; // Garante que esteja vazio se não houver texto depois
                          }

                        // Define o conteúdo renderizável como a estrutura de lista
                        contentToRender = (
                          <>
                            {renderContentWithLinks(introText)} {/* Processa links no texto antes */}
                            <ul className="time-slots-list">
                              {slots.map((slot, i) => (
                                <li key={i}>{slot}</li>
                              ))}
                            </ul>
                            {renderContentWithLinks(afterText)} {/* Processa links no texto depois */}
                          </>
                        );

                    } else {
                        // Se isTimeSlotMessage foi true mas parse falhou, renderiza normalmente com links
                        console.warn("isTimeSlotMessage foi true, mas parseTimeSlots não encontrou slots:", msg.content);
                        contentToRender = renderContentWithLinks(msg.content);
                    }
                  } else {
                    // Se NÃO for uma mensagem de slot, renderiza normalmente com links
                    contentToRender = renderContentWithLinks(msg.content);
                  }
              } else {
                  // Fallback se msg.content não for uma string
                  contentToRender = "Formato de mensagem inválido";
                  console.error("Mensagem recebida sem conteúdo string:", msg);
              }

              // Renderiza a div da mensagem com o conteúdo processado
              return (
                <div key={index} className={`message ${msg.role}`}>
                  {contentToRender}
                </div>
              );
            })
          }
          <div ref={messagesEndRef} /> {/* Para o auto-scroll */}
        </div>
        <div className="input-area">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Digite sua mensagem..."
          />
          <button onClick={handleSend} >Send</button>
        </div>
      </div>
    </div>
  );
}

export default App;