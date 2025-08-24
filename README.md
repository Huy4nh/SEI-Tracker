# 🤖 SEI Tracker - Blockchain Telegram Bot with Claude AI & SEI MCP

A sophisticated Telegram bot powered by Anthropic's Claude 3.7 Sonnet, integrated with SEI Model Context Protocol (MCP) for real-time SEI blockchain data access. Features intelligent table rendering, web search capabilities, and seamless MCP server integration.

## ✨ Key Features

- **🤖 AI-Powered Chat**: Claude 3.7 Sonnet integration for intelligent responses
- **🔗 SEI MCP Integration**: Model Context Protocol support for blockchain data access
- **📊 Smart Table Rendering**: Automatic conversion of data tables to PNG images
- **🌐 Web Search**: Real-time web search capabilities via Anthropic's beta features
- **📱 Telegram Bot**: Full-featured bot with MarkdownV2 support
- **⚡ FastAPI Backend**: High-performance web framework with webhook support
- **🎨 Customizable UI**: Light/dark themes for table images
- **🔄 Streaming Responses**: Real-time streaming of AI responses

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Telegram Bot  │    │   Claude AI     │    │   MCP Bridge    │
│   (aiogram)     │◄──►│   (Anthropic)   │◄──►│   (MCP SDK)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI App   │    │  Table Tools    │    │  SEI MCP Server │
│   (Webhook)     │    │  (PIL/Pillow)   │    │  (Node.js)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+** (3.10+ recommended)
- **Node.js 18+** (for MCP server)
- **Telegram Bot Token** (from [@BotFather](https://t.me/botfather))
- **Anthropic API Key** (from [Anthropic Console](https://console.anthropic.com/))

### 1. Clone & Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd readme

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 2. Install Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install Python dependencies
pip install -r requirements.txt

# Install MCP server (optional, for blockchain data)
npm install -g @sei-js/mcp-server
```

### 3. Environment Configuration

```bash
# Copy environment template
cp env.example .env

# Edit .env file with your credentials
nano .env  # or use your preferred editor
```

**Required Environment Variables:**

```bash
# Telegram Bot Configuration
BOT_TOKEN=your_telegram_bot_token_here

# Anthropic API Configuration  
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Webhook Configuration (for production)
WEBHOOK_HOST=https://your-domain.com
WEBHOOK_PATH=/webhook

# MCP Configuration (optional)
MCP_SERVERS_CONFIG_PATH=mcp.json

# Feature Flags
ENABLE_WEB_SEARCH=1
ENABLE_MCP=1

# Development Settings
DEBUG=1
LOG_LEVEL=INFO
```

### 4. MCP Server Configuration (Optional)

If you want to access SEI blockchain data, configure the MCP server:

```json
// mcp.json
{
  "mcpServers": {
    "sei": {
      "command": "npx",
      "args": ["-y", "@sei-js/mcp-server"],
      "env": {
        "PRIVATE_KEY": "Your SEI private wallet key here"
      }
    }
  }
}
```

**⚠️ Security Note**: Never commit your private keys to version control!

### 5. Run the Application

#### Development Mode (Local)
```bash
# Start the bot locally
python main.py
```

#### Production Mode (Webhook)
```bash
# Set webhook URL in .env
WEBHOOK_HOST=https://your-domain.com
WEBHOOK_PATH=/webhook

# Start with uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 🛠️ Installation Scripts

### Windows
```cmd
# Run the automated installer
install.bat

# Start the application
run.bat
```

### macOS/Linux
```bash
# Make scripts executable
chmod +x install.sh run.sh

# Run installer
./install.sh

# Start application
./run.sh
```

## 📁 Project Structure

```
readme/
├── 📄 main.py                 # Main FastAPI application & Telegram bot
├── 🤖 chatbot.py             # Claude AI integration & chat logic
├── 🔗 mcp_bridge.py          # MCP server connection bridge
├── ⚙️ mcp.json               # MCP server configuration
├── 🛠️ tools/                 # Utility tools
│   ├── 📊 table.py           # Table formatting utilities
│   ├── 🖼️ table_image.py     # PNG table rendering
│   └── __init__.py           # Tool definitions
├── 🔧 function/               # Helper functions
│   └── explore.py            # Exploration utilities
├── 📋 requirements.txt        # Python dependencies
├── 🔐 env.example            # Environment template
├── 📚 README.md              # This file
├── 📄 LICENSE                # MIT License
├── 🚀 install.*              # Installation scripts
├── ▶️ run.*                  # Runtime scripts
└── 🔧 .gitignore             # Git ignore rules
```

## 🔧 Configuration Details

### Telegram Bot Setup

1. **Create Bot**: Message [@BotFather](https://t.me/botfather) on Telegram
2. **Get Token**: Use `/newbot` command and save the token
3. **Configure Webhook** (Production):
   ```bash
   # Set webhook URL
   curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
        -H "Content-Type: application/json" \
        -d '{"url": "https://your-domain.com/webhook"}'
   ```

### Anthropic API Setup

1. **Create Account**: Sign up at [Anthropic Console](https://console.anthropic.com/)
2. **Generate API Key**: Create a new API key
3. **Enable Beta Features**: Ensure web search is enabled for your account

### MCP Server Setup (Optional)

1. **Install Node.js**: Ensure Node.js 18+ is installed
2. **Install MCP Server**: `npm install -g @sei-js/mcp-server`
3. **Configure Wallet**: Add your SEI private key to `mcp.json`
4. **Test Connection**: Run `python probe_mcp.py` to verify

## 🚀 Usage Examples

### Basic Chat
```
User: "Hello, what can you do?"
Bot: "I'm a SEI blockchain assistant powered by Claude AI. I can help you with blockchain queries, create data tables, and access real-time SEI network information through MCP tools."
```

### Table Creation
```
User: "Show me a table of top 5 cryptocurrencies"
Bot: [Creates and sends PNG table image]
```

### Blockchain Queries
```
User: "What's the current SEI network status?"
Bot: [Uses MCP tools to fetch real-time data]
```

### Web Search
```
User: "What are the latest developments in SEI blockchain?"
Bot: [Performs web search and provides current information]
```

## 🧪 Testing & Development

### Run Tests
```bash
# Install test dependencies
pip install pytest

# Run tests
pytest
```

### Code Quality
```bash
# Install development tools
pip install black flake8

# Format code
black .

# Lint code
flake8
```

### Debug Mode
```bash
# Enable debug logging
export DEBUG=1
export LOG_LEVEL=DEBUG

# Run with verbose output
python main.py
```

## 🔍 Troubleshooting

### Common Issues

#### 1. Bot Not Responding
```bash
# Check bot token
echo $BOT_TOKEN

# Verify webhook status
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

#### 2. MCP Connection Failed
```bash
# Test MCP bridge
python probe_mcp.py

# Check Node.js installation
node --version
npm --version
```

#### 3. Image Generation Issues
```bash
# Check Pillow installation
python -c "from PIL import Image; print('Pillow OK')"

# Verify output directory permissions
ls -la out_images/
```

#### 4. Claude API Errors
```bash
# Verify API key
echo $ANTHROPIC_API_KEY

# Check API quota
# Visit: https://console.anthropic.com/account/usage
```

### Log Analysis
```bash
# Enable detailed logging
export LOG_LEVEL=DEBUG

# Monitor logs in real-time
tail -f logs/app.log  # if logging to file
```

## 🚀 Deployment

### Docker Deployment
```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Production Considerations

1. **Environment Variables**: Use secure environment management
2. **SSL/TLS**: Enable HTTPS for webhook endpoints
3. **Rate Limiting**: Implement API rate limiting
4. **Monitoring**: Add health checks and logging
5. **Backup**: Regular database and configuration backups

## 🤝 Contributing

We welcome contributions! Please follow these steps:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/AmazingFeature`)
3. **Commit** your changes (`git commit -m 'Add AmazingFeature'`)
4. **Push** to the branch (`git push origin feature/AmazingFeature`)
5. **Open** a Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add tests for new features
- Update documentation as needed
- Use meaningful commit messages

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Anthropic](https://anthropic.com/) - Claude AI API
- [Telegram Bot API](https://core.telegram.org/bots/api) - Bot platform
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [MCP](https://modelcontextprotocol.io/) - Model Context Protocol
- [SEI Network](https://sei.io/) - Blockchain platform

## 🆘 Support

### Getting Help

1. **Check Issues**: Search existing [Issues](../../issues)
2. **Create Issue**: Report bugs or request features
3. **Documentation**: Review this README and code comments
4. **Community**: Join SEI community channels

### Contact Information

- **Contact**: huynhnguyenhuyanh.work@gmail.com
- **Website**: seitracker.cloud
- **Support Us**: https://dorahacks.io/buidl/31445
- **Documentation**: This README
- **SEI Network**: [sei.io](https://sei.io/)
### Check out here
- **Product**:https://t.me/SEITracker_AI_bot
---
*Last updated: August 2025* 
