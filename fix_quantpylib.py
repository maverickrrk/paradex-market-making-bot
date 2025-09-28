#!/usr/bin/env python3
"""
Comprehensive Post-Installation Fix for quantpylib Compatibility Issues
=====================================================================

This script fixes ALL known compatibility issues between quantpylib and the Paradex market making bot.
Run this script after installing quantpylib in a new virtual environment.

Issues Fixed:
============

1. BARS IMPORT ISSUE (feed.py)
   Error: NameError: name 'bars' is not defined. Did you mean: 'vars'?
   Cause: Line 11 has commented import but line 663 still uses bars.TimeBars
   Fix: Replace 'bar_cls=bars.TimeBars,' with 'bar_cls=None,'

2. LOB CONSTRUCTOR ISSUE (paradex.py)
   Error: LOB.__init__() got an unexpected keyword argument 'depth'
   Cause: Paradex wrapper passes depth/buffer_size params that LOB doesn't accept
   Fix: Create LOB with correct constructor: LOB(bids=np.array([]), asks=np.array([]))

3. LOB UPDATE METHOD ISSUE (paradex.py)
   Error: 'LOB' object has no attribute 'update'
   Cause: Paradex wrapper calls ob.update() method that doesn't exist
   Fix: Replace with direct attribute assignment: ob.bids = bids; ob.asks = asks

4. MISSING AS_DICT METHOD (lob.py)
   Error: 'LOB' object has no attribute 'as_dict'
   Cause: Paradex wrapper calls ob.as_dict() method that doesn't exist
   Fix: Add as_dict() method to LOB class

Additional Configuration Issues Solved:
======================================

5. ENVIRONMENT LOADING (.env not loaded)
   Issue: Bot connects to prod instead of testnet
   Fix: Force load .env from project root with explicit path

6. ORDER SIZE TOO SMALL (Paradex minimum requirements)
   Issue: Orders rejected for being below $100 minimum
   Fix: Set order_value >= 100 in config

7. PRICE/SIZE PRECISION (Paradex formatting requirements)
   Issue: Orders rejected for incorrect decimal places
   Fix: Round prices to 2 decimals, sizes to 4 decimals

This script ensures the bot works correctly from a fresh quantpylib installation.
"""

import os
import sys
from pathlib import Path

def fix_quantpylib_feed():
    """Fix the bars import issue in quantpylib feed.py"""
    
    # Find the quantpylib installation path
    try:
        import quantpylib
        quantpylib_path = Path(quantpylib.__file__).parent
        feed_file = quantpylib_path / "hft" / "feed.py"
        
        if not feed_file.exists():
            print(f"❌ Could not find feed.py at: {feed_file}")
            return False
            
        print(f"📁 Found quantpylib at: {quantpylib_path}")
        print(f"🔧 Fixing file: {feed_file}")
        
        # Read the current content
        with open(feed_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if already fixed
        if 'bar_cls=None,' in content:
            print("✅ feed.py already fixed!")
            return True
            
        # Apply the fix
        original_line = 'bar_cls=bars.TimeBars,'
        fixed_line = 'bar_cls=None,'
        
        if original_line in content:
            content = content.replace(original_line, fixed_line)
            
            # Write back the fixed content
            with open(feed_file, 'w', encoding='utf-8') as f:
                f.write(content)
                
            print("✅ Successfully fixed quantpylib bars import issue!")
            print(f"   Changed: {original_line}")
            print(f"   To:      {fixed_line}")
            return True
        else:
            print(f"⚠️  Could not find expected line: {original_line}")
            print("   The quantpylib version might have changed.")
            return False
            
    except ImportError:
        print("❌ quantpylib not found. Please install it first:")
        print("   pip install git+https://github.com/sumitabh1710/quantpylib.git")
        return False
    except Exception as e:
        print(f"❌ Error fixing quantpylib: {e}")
        return False

def fix_quantpylib_paradex():
    """Fix the LOB constructor and update issues in quantpylib paradex.py"""
    
    try:
        import quantpylib
        quantpylib_path = Path(quantpylib.__file__).parent
        paradex_file = quantpylib_path / "wrappers" / "paradex.py"
        
        if not paradex_file.exists():
            print(f"❌ Could not find paradex.py at: {paradex_file}")
            return False
            
        print(f"🔧 Fixing file: {paradex_file}")
        
        # Read the current content
        with open(paradex_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if already fixed
        if 'ob.bids = bids' in content and 'ob = LOB(bids=np.array([]), asks=np.array([]))' in content:
            print("✅ paradex.py already fixed!")
            return True
            
        # Apply fix 1: LOB constructor
        original_line1 = 'ob = LOB(depth=depth,buffer_size=buffer_size,apply_shadow_depth=apply_shadow_depth)'
        fixed_lines1 = '''# Create LOB with empty numpy arrays (will be populated by updates)
        import numpy as np
        ob = LOB(bids=np.array([]), asks=np.array([]))'''
        
        if original_line1 in content:
            content = content.replace(original_line1, fixed_lines1)
            print("✅ Fixed LOB constructor issue")
        
        # Apply fix 2: LOB update method
        original_line2 = 'ob.update(timestamp=ts,bids=bids,asks=asks,is_snapshot=is_snapshot,is_sorted=False)'
        fixed_lines2 = '''# Update LOB by creating new instance with updated data
            ob.bids = bids
            ob.asks = asks'''
        
        if original_line2 in content:
            content = content.replace(original_line2, fixed_lines2)
            print("✅ Fixed LOB update method issue")
            
            # Write back the fixed content
            with open(paradex_file, 'w', encoding='utf-8') as f:
                f.write(content)
                
            print("✅ Successfully fixed quantpylib paradex.py issues!")
            return True
        else:
            print(f"⚠️  Could not find expected lines in paradex.py")
            print("   The quantpylib version might have changed.")
            return False
            
    except Exception as e:
        print(f"❌ Error fixing quantpylib paradex: {e}")
        return False

def fix_quantpylib_lob():
    """Fix the missing as_dict method in quantpylib lob.py"""
    
    try:
        import quantpylib
        quantpylib_path = Path(quantpylib.__file__).parent
        lob_file = quantpylib_path / "hft" / "lob.py"
        
        if not lob_file.exists():
            print(f"❌ Could not find lob.py at: {lob_file}")
            return False
            
        print(f"🔧 Fixing file: {lob_file}")
        
        # Read the current content
        with open(lob_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if already fixed
        if 'def as_dict(self)' in content:
            print("✅ lob.py already fixed!")
            return True
            
        # Apply the fix - add as_dict method
        original_end = 'return (bid_vwap + ask_vwap) / 2.0'
        fixed_end = '''return (bid_vwap + ask_vwap) / 2.0

    def as_dict(self) -> dict:
        """Returns the LOB data as a dictionary format."""
        return {
            'bids': self.bids.tolist() if self.bids.size > 0 else [],
            'asks': self.asks.tolist() if self.asks.size > 0 else [],
            'mid': self.get_mid(),
            'spread': self.get_spread()
        }'''
        
        if original_end in content:
            content = content.replace(original_end, fixed_end)
            
            # Write back the fixed content
            with open(lob_file, 'w', encoding='utf-8') as f:
                f.write(content)
                
            print("✅ Successfully added as_dict method to LOB class!")
            return True
        else:
            print(f"⚠️  Could not find expected line: {original_end}")
            print("   The quantpylib version might have changed.")
            return False
            
    except Exception as e:
        print(f"❌ Error fixing quantpylib lob: {e}")
        return False

def main():
    print("🔧 Paradex Market Making Bot - Comprehensive quantpylib Fix Script")
    print("=" * 70)
    print("This script fixes ALL known compatibility issues with quantpylib.")
    print("Run this after every fresh quantpylib installation.")
    print("=" * 70)
    
    print("\n1️⃣ Fixing feed.py (bars import issue)...")
    print("   Issue: NameError: name 'bars' is not defined")
    print("   Fix: Replace 'bars.TimeBars' with 'None'")
    success1 = fix_quantpylib_feed()
    
    print("\n2️⃣ Fixing paradex.py (LOB constructor & update issues)...")
    print("   Issue: LOB.__init__() got unexpected keyword argument 'depth'")
    print("   Issue: 'LOB' object has no attribute 'update'")
    print("   Fix: Correct LOB constructor and update method calls")
    success2 = fix_quantpylib_paradex()
    
    print("\n3️⃣ Fixing lob.py (missing as_dict method)...")
    print("   Issue: 'LOB' object has no attribute 'as_dict'")
    print("   Fix: Add as_dict method to LOB class")
    success3 = fix_quantpylib_lob()
    
    overall_success = success1 and success2 and success3
    
    print("\n" + "=" * 70)
    if overall_success:
        print("🎉 ALL FIXES APPLIED SUCCESSFULLY!")
        print("✅ quantpylib is now fully compatible with the Paradex bot")
        print("✅ You can now run: python -m src.main")
        print("\nNext steps:")
        print("1. Ensure your .env file has PARADEX_ENV=testnet")
        print("2. Ensure your config has order_value >= 100 (Paradex minimum)")
        print("3. Run the bot: python -m src.main")
    else:
        print("💥 SOME FIXES FAILED!")
        print("❌ Manual intervention may be required")
        print("\nFailed fixes:")
        if not success1:
            print("   - feed.py fix failed (bars import issue)")
        if not success2:
            print("   - paradex.py fix failed (LOB constructor/update issues)")
        if not success3:
            print("   - lob.py fix failed (missing as_dict method)")
        print("\nPlease check the error messages above and apply fixes manually.")
    
    print("=" * 70)
    return 0 if overall_success else 1

if __name__ == "__main__":
    sys.exit(main())
