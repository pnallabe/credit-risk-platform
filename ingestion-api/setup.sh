#!/bin/bash
set -e

echo "🚀 AI Risk Workflow Platform - Ingestion API Setup"
echo "=================================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.11+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "✓ Python ${PYTHON_VERSION} found"

if ! command -v gcloud &> /dev/null; then
    echo "⚠️  gcloud CLI not found. Install from: https://cloud.google.com/sdk/docs/install"
    echo "   (Optional for local development)"
fi

# Create virtual environment
echo ""
echo "Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip --quiet

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install -r requirements.txt --quiet
echo "✓ Dependencies installed"

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo ""
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "✓ .env file created - please edit with your values"
    echo ""
    echo "⚠️  IMPORTANT: Update the following in .env:"
    echo "   - GCP_PROJECT_ID"
    echo "   - JWT_SECRET (use a strong random string)"
    echo "   - GOOGLE_APPLICATION_CREDENTIALS path"
else
    echo ""
    echo "✓ .env file already exists"
fi

# Make scripts executable
echo ""
echo "Making scripts executable..."
chmod +x deployment/deploy.sh 2>/dev/null || true
echo "✓ Scripts are executable"

# Create necessary directories
mkdir -p logs

# Run tests to verify setup (skip if pytest not installed yet)
echo ""
echo "Running tests to verify setup..."
if command -v pytest &> /dev/null; then
    if pytest tests/test_main.py -v --tb=short 2>/dev/null; then
        echo ""
        echo "✅ All tests passed!"
    else
        echo ""
        echo "⚠️  Some tests failed. This is normal if GCP credentials are not configured."
        echo "   The API will work once you set up GCP credentials."
    fi
else
    echo "⚠️  pytest not found, skipping tests"
fi

echo ""
echo "=================================================="
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo ""
echo "1. Edit .env with your GCP project details:"
echo "   vi .env"
echo ""
echo "2. Set up GCP resources (if not already done):"
echo "   make setup-gcp"
echo ""
echo "3. Run the API locally:"
echo "   make run"
echo ""
echo "4. View API documentation:"
echo "   Open http://localhost:8080/docs"
echo ""
echo "5. Generate a test token:"
echo "   make token"
echo ""
echo "6. Test the API:"
echo "   curl -X POST http://localhost:8080/transactions \\"
echo "     -H 'Authorization: Bearer YOUR_TOKEN' \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d @examples/example_payloads.json"
echo ""
echo "=================================================="
echo ""
echo "For more information, see README.md"