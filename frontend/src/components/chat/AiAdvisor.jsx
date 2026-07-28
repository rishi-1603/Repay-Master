import React, { useState } from 'react';
import { MessageSquare } from 'lucide-react';
import { chatWithAI } from '../../services/api';

export default function AiAdvisor({ loans }) {
  const [aiMessage, setAiMessage] = useState('');
  const [aiReply, setAiReply] = useState('');

  const handleAiChat = async () => {
    if (!aiMessage) return;
    setAiReply("Thinking...");
    try {
      const res = await chatWithAI(aiMessage, { loans });
      setAiReply(res.reply);
    } catch (e) {
      setAiReply("Failed to reach AI Advisor.");
    }
  };

  return (
    <div className="bg-gradient-to-br from-indigo-900 to-primary p-6 rounded-2xl shadow-xl text-white">
      <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
        <MessageSquare size={20} /> AI Financial Advisor
      </h2>
      <p className="text-sm text-indigo-200 mb-6">Ask me anything about your loans, refinancing, or repayment strategies.</p>
      
      <div className="space-y-4 mb-4">
        <div className="bg-white/10 p-4 rounded-xl text-sm min-h-[100px] max-h-[300px] overflow-y-auto">
          {aiReply || "I'm your Gemini-powered advisor. How can I help you today?"}
        </div>
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Can I repay early?"
          value={aiMessage}
          onChange={(e) => setAiMessage(e.target.value)}
          className="flex-1 bg-white/20 border-none rounded-lg px-4 py-2 text-white placeholder-indigo-300 focus:ring-2 focus:ring-secondary"
        />
        <button onClick={handleAiChat} className="bg-secondary text-white px-4 py-2 rounded-lg font-medium hover:bg-emerald-600 transition-colors">
          Ask
        </button>
      </div>
    </div>
  );
}
